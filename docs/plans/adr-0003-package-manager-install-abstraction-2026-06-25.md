# ADR-0003: PackageManager install abstraction for optional components

| Field | Value |
|---|---|
| Status | accepted |
| Date | 2026-06-25 |

## Context

`installers/components.py` defines self-registering `OptionalComponent`
subclasses (see ADR-0002 for the extension point). Today each component's
`install(manager)` does the actual installation by one of three ad-hoc means:

- calling a hand-written free function in `installers/debian.py` /
  `installers/macos.py` (`1password`, `docker`, `cmdl-tools`, `cuda`, `llvm`,
  `mac-brew`);
- branching on `manager.os_type` and calling either `brew install` or a
  debian helper (`btm`, `fdfind`);
- inlining a `curl -o <tempfile>` → `bash <tempfile>` → `unlink` dance
  (`claude`, `node`, `rustup`, `codegraph`).

Two problems follow. First, the "download a script to a temp file, run it,
clean up" pattern is copy-pasted across at least four components. Second, the
knowledge of *how to install on a given platform* is smeared between the
component, the per-OS helper modules, and inline branches — a component that
installs on both Debian and macOS has its logic split across two places, and
the package name differs per platform (e.g. 1Password is a `.deb` URL on
Debian, a cask on macOS).

We want a single abstraction for "install backend" so a component can declare
*what it is called / how it is fetched* per backend, and the orchestrator
decides *which backend to use* for the current environment.

Note the terminology collision: `DotfilesManager` (in `main.py`) is the
orchestrator. The new concept — a package-manager backend — is named
**`PackageManager`** to keep the two distinct. `DotfilesManager` remains the
context object passed into installs.

## Decision

Introduce a `PackageManager` abstraction and make `OptionalComponent`
declarative-first, keeping an imperative escape hatch for multi-step installs.

### 1. Hybrid component model: declarative table + imperative override

A component is, by default, *data*: a mapping from package-manager id to an
install spec.

```python
class Ripgrep(OptionalComponent):
    name = "ripgrep"
    description = "ripgrep"
    groups = frozenset({"all"})
    installs = {
        "apt":  "ripgrep",   # bare string shorthand = package name
        "brew": "ripgrep",
    }
```

The base-class `install()` resolves this table automatically. Components whose
install is genuinely multi-step (e.g. `docker`'s `groupadd`/`usermod`/ppa
setup, `llvm`'s `update-alternatives`) **override `install(ctx)`** as they do
today. The two paths coexist: declarative for the common case, imperative for
the awkward ~20%.

### 2. The orchestrator selects the PackageManager, not the component

Selection is `DotfilesManager`'s responsibility. It holds a registry of
`PackageManager` instances, detects the OS, and for a given component:

1. filters to managers that **support the current OS** and that the component
   has a spec for (`installs` key present);
2. picks the **highest-priority** match, where native package managers
   (`apt`, `brew`) rank ahead of `scripts`. So a component listing both `apt`
   and `scripts` uses `apt` on Debian and falls back to `scripts` elsewhere;
3. calls `manager.install(ctx, spec)` with the component's spec for that id.

The component never chooses its own backend.

### 3. `supported_os` is derived, not declared

For declarative components, applicability on the current OS is computed as
"some listed manager supports this OS" (the union of `supported_os` across the
managers named in `installs`). The explicit `supported_os` field is dropped
for declarative components — it cannot drift out of sync with the install
entries. Imperative-override components, which bypass the table, keep an
explicit `supported_os`.

### 4. Per-manager structured specs, with a bare-string shorthand

Each `PackageManager` defines and validates **its own** spec type; a bare
string is accepted as shorthand for that manager's primary parameter:

- `apt` / `brew`: a string is the package name. A richer spec (e.g.
  `Deb(url=...)`) lets the same `apt` manager express "download a `.deb` and
  `apt install -f`" (1Password) without exploding into separate `apt` / `deb`
  / `cask` manager ids.
- `scripts`: a `Script(url, interpreter="bash", args=[])` spec. URL alone is
  insufficient — `rustup` needs `sh` + `-y --default-toolchain stable
  --profile default --no-modify-path`; `codegraph` needs `sh`; `claude`/`nvm`
  need `bash`.

### 5. The `scripts` PackageManager: minimal spec, reusable backend

`scripts.install(ctx, Script(...))` downloads the URL to a temp directory, runs
`<interpreter> <tempfile> <args...>`, and cleans up — respecting
`ctx.dry_run`. The spec is kept **minimal** (`url` / `interpreter` / `args`):
no `skip_if` / `post` / `upgrade_cmd` hooks. Component-specific logic
(idempotency checks, post-install steps, advisory logs) stays in imperative
overrides, which keeps the declarative path honest.

To avoid re-duplicating the curl-tempfile-run dance, `DotfilesManager` exposes
`ctx.package_manager(id)` so an imperative override can **reuse** a manager:

```python
class Rustup(OptionalComponent):
    name = "rustup"
    supported_os = None
    def install(self, ctx):
        if shutil.which("rustup"):
            ctx.run_command(["rustup", "default", "stable"]); return
        ctx.package_manager("scripts").install(
            ctx, Script(url="https://sh.rustup.rs", interpreter="sh",
                        args=["-y", "--default-toolchain", "stable",
                              "--profile", "default", "--no-modify-path"]))
```

Thus `scripts` is both the backend for declarative script components (`claude`)
and a reusable helper for the imperative ones (`node`, `rustup`, `codegraph`).

### 6. PackageManager interface and registration

`PackageManager` mirrors the self-registering pattern of `OptionalComponent`:
a subclass declares `id`, `supported_os` (or `None` for all), `priority`, and
implements `install(ctx, spec)`. Declaring the subclass registers it; no
parallel lookup table.

## Consequences

- The "download a script, run it, clean up" logic lives in exactly one place
  (`scripts` manager); `claude`/`node`/`rustup`/`codegraph` stop copy-pasting
  it.
- Simple components (`ripgrep`, `fdfind`, `bottom`, `1password`) become a few
  lines of data with no per-component code and no OS branching.
- Cross-platform package-name differences are expressed in one table per
  component instead of being split across `debian.py` / `macos.py` / inline
  branches.
- `supported_os` for declarative components can no longer drift from reality;
  it is computed from the managers actually listed.
- Cost: two component code paths (declarative vs. imperative override) to
  understand, and per-manager spec types to define and validate. The
  "bare string = primary parameter" convention must be documented per manager.
- Cost: a bit of implicit behavior — OS support and backend choice are inferred
  by the orchestrator rather than spelled out on each component.
- ADR-0002's `node` toolchain decision (nvm → Node LTS → pnpm) is unchanged in
  intent; the `node` component is re-expressed as an imperative override that
  reuses the `scripts` manager for the nvm install step.
- `installers/debian.py` / `installers/macos.py` free functions remain only for
  the imperative-override components; single-package helpers are absorbed into
  the declarative tables and can be deleted as components migrate.
- Migration can be incremental: components move to the declarative table one at
  a time; until migrated, an un-migrated component keeps its current
  `install()` override and explicit `supported_os`.
```

