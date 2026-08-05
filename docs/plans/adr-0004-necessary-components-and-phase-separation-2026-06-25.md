# ADR-0004: Necessary components and main-path phase separation

| Field | Value |
|---|---|
| Status | accepted |
| Date | 2026-06-25 |

## Context

`DotfilesManager.run()` (in `main.py`) executes the bootstrap in three implicit
groups: OS bootstrap (`bootstrap_debian` / `bootstrap_macos`), then
`run_legacy_scripts()`, then `run_optional_installers()`. ADR-0002/ADR-0003 gave
*optional* software a clean home — self-registering `OptionalComponent`
subclasses driven by the `PackageManager` install abstraction — but the
defaulted-on software is still hand-rolled inside `run_legacy_scripts()`:

```python
def run_legacy_scripts(self):
    self.config_ohmyzsh(...)   # oh-my-zsh + antigen + zsh plugins
    self.install_fzf()          # fzf
    self.install_starship(...)  # starship
    staging = _dotfiles_staging_dir()
    ...                         # stage_dotfiles + link_dotfiles (ADR-0001)
```

This conflates **two unrelated concerns** under one method named after how it
grew ("legacy scripts") rather than what it does:

1. installing shell tooling that is *necessary* but is, mechanically, the same
   kind of thing as an optional component (a tool install — fzf and starship are
   even script-based installs that the `scripts` `PackageManager` already
   handles);
2. the dotfiles **migration** (stage → link) defined by ADR-0001, which is a
   filesystem operation, not a software install.

Three problems follow. First, the necessary installs get none of the
declarative/imperative `PackageManager` machinery from ADR-0003, so a future
native package (`apt install fzf`, `brew install starship`) cannot be expressed
as data. Second, the order of the shell installs is correctness-critical yet is
an invisible side effect of statement order inside a method. Third — and most
insidiously — `config_ohmyzsh()` runs the upstream oh-my-zsh installer, which
writes a **real** `~/.zshrc`, and `link_dotfiles()` later **skips pre-existing
real files**. So the repo's own `.zshrc` (the file that actually sources
oh-my-zsh, fzf, and starship) silently loses to an installer-generated default.
The bug is masked today because it lives inside one method; any clean split
forces the ownership question into the open.

We want the necessary installs to reuse the component machinery, the migration
to stand on its own, and the rc-file ownership and ordering to be explicit.

## Decision

Extract a `NecessaryComponent` catalog that shares the install machinery with
`OptionalComponent`, and split `run()` into four explicitly named phases.

### 1. Four named phases, replacing `run_legacy_scripts()`

`run()` runs, in order:

```
bootstrap_*()              # OS prerequisites — stays in main.py (ADR-0003 §7)
run_necessary_components()  # ordered, always-run tool installs (NEW)
migrate_dotfiles()          # stage_dotfiles + link_dotfiles (ADR-0001), renamed
run_optional_installers()   # user-selected OptionalComponent registry (existing)
```

`run_legacy_scripts()` is retired. OS bootstrap stays a `DotfilesManager`
prerequisite per ADR-0003 §7 — it is *not* folded into the component system.

### 2. Shared `Component` base; two subclasses

The **install machinery** is pulled up into a shared `Component` base:
`effective_supported_os()`, `applicable()`, the declarative `install()` that
resolves the `installs` table via `ctx.select_manager(...)`, the
`ctx.package_manager(id)` reuse path, and `run()`. `OptionalComponent` and
`NecessaryComponent` both subclass it.

The **registry mechanics** (`_registry`, `__init_subclass__`, `names()`,
`alias_groups()`, `resolve()`, `get()`) stay on `OptionalComponent`, not the
shared base — a `NecessaryComponent` is instantiated directly from the
`NECESSARY` tuple, so it needs no registry, and hoisting `_registry` to
`Component` would pollute the optional catalog with necessary classes.

The two subclasses differ only in *lifecycle*, which is exactly the asymmetry
that justifies separate classes rather than a `required = True` flag on one
registry:

| | `OptionalComponent` | `NecessaryComponent` |
|---|---|---|
| Selection | user-chosen (`--optional-components`) | always run |
| Order | registration order, set-based `resolve()` | explicit, strict |
| Missing on OS | silent skip | still skip-if-N/A, but never user-deselected |
| `resolve()`/`alias_groups()`/`names()` plumbing | yes | no |

Folding both into one class with a `required`/`order` flag would force every
`resolve()` / `names()` / `alias_groups()` path to special-case the required
entries — leaky. A standalone `NecessaryComponent` that re-implemented installs
would duplicate ADR-0003's machinery. The shared base captures the real reuse
(install backends) while each subclass stays honest about its own semantics.

### 3. Necessary order is one explicit tuple, not registration order

Necessary components do **not** self-register into an order-bearing registry.
Their sequence is a single reviewable literal:

```python
NECESSARY = (OhMyZsh, Fzf, Starship)
```

`run_necessary_components()` iterates this tuple and calls `.run(ctx)` on each.
For ~3 curated, order-critical installs, self-registration would hide the one
property that matters; a reordering must show up as an obvious one-line diff,
not a subtle class move. (Contrast `OptionalComponent`, where registration order
is incidental and the registry's auto-assembly genuinely pays off across ~14
entries.) `NecessaryComponent` still subclasses the shared base for the install
machinery; it simply doesn't need the `resolve()` registry plumbing.

### 4. The migration phase owns shell rc files; necessary installs do not

Invariant: **necessary components install binaries/frameworks only; shell rc
files belong to the migration phase.** The repo's `.zshrc` is canonical.

Concretely, `OhMyZsh.install()` runs the upstream installer with
`KEEP_ZSHRC=yes` so it installs the framework without ever writing `~/.zshrc`.
To pass that var cleanly as a list command, `DotfilesManager.run_command` gains
an `env` parameter (overlaid onto the inherited environment) — retiring the
"export inline in a shell string" workaround the wrapper previously forced
(cf. `install_homebrew`).
The order stays `necessary → migration`, and `link_dotfiles()` then links the
repo's `.zshrc` (which sources oh-my-zsh, fzf, and starship) authoritatively.
This removes the latent "installer default silently wins" bug rather than
enshrining it across the new phase boundary.

### 5. Activation is a final advisory notice, not re-exec

oh-my-zsh / starship / fzf only take effect in a fresh interactive shell, but a
bootstrap process cannot activate the parent terminal's environment — sourcing
`~/.zshrc` in a subprocess is inert, and re-exec'ing is fragile and surprising.
`run()` ends with a single advisory notice ("open a new shell or `exec zsh` to
activate …"). This is purely informational and does **not** affect the
fully-automated install: the later phases never shell out to
`starship`/`fzf`/`zsh`, and optional installers that need a runtime source it
themselves in-process (e.g. `node` does `export NVM_DIR; . nvm.sh; nvm install`
in one `bash -c`). No inter-phase dependency on an activated shell exists.

### 6. File layout

`NecessaryComponent`, the `OhMyZsh`/`Fzf`/`Starship` classes, and the `NECESSARY`
tuple live in `installers/components.py` alongside the optional catalog —
consistent with ADR-0003 §7's consolidation of all component logic into one
file. The `config_ohmyzsh` / `install_fzf` / `install_starship` methods move off
`DotfilesManager` and become the components' `install(ctx)` bodies (imperative
overrides, since each is multi-step). `stage_dotfiles` / `link_dotfiles` /
`_staging_has_unlinked_items` stay on `DotfilesManager` as the `migrate_dotfiles`
phase — they are filesystem operations, not component installs.

## Consequences

- The main path reads as four named phases with a single concern each, instead
  of a `run_legacy_scripts()` method whose name describes its history.
- The shell-rc ownership bug is fixed, not relocated: the repo's `.zshrc` wins
  via `KEEP_ZSHRC=yes`, and the rule is written down as an invariant.
- Necessary installs gain the `PackageManager` machinery: fzf/starship can later
  be expressed as declarative `installs = {...}` entries if native packages are
  preferred, with no new code.
- The necessary install order is reviewable in one line; reordering is a visible
  diff.
- Cost: a refactor pulling registry/install mechanics into a shared `Component`
  base, and a third component lifecycle (necessary) to understand alongside
  declarative and imperative-override optionals.
- Cost: mild asymmetry — optional components self-register while necessary ones
  are listed in an explicit tuple. This is intentional and reflects
  curated-and-ordered vs. user-selected.
- ADR-0001's staging/linking strategy is unchanged in behavior; only the
  enclosing method is renamed (`migrate_dotfiles`) and lifted to its own phase.
- ADR-0003 §7's "core bootstrap is not a component" line is preserved: OS
  bootstrap stays in `main.py`. This ADR adds a tier *between* bootstrap and
  optional, it does not move bootstrap into the component system.
