# ADR-0010: Plan-first bootstrap with a single interactive clearance

| Field | Value |
|---|---|
| Status | accepted |
| Date | 2026-08-04 |

## Context

`./bootstrap.sh` is the one command a new machine runs, and it is far from
inert: it installs Lix as root, edits the system `/etc/nix/nix.conf`, restarts
the nix-daemon, changes the login shell with `chsh`, installs opt-in system
software (docker/cuda/nvidia/llvm), fetches and executes remote installer
scripts, and moves existing `$HOME` files aside (`*.backup` from Home Manager,
`*.pre-dotfiles.bak` from the ADR-0008 link map). Until now it did all of that
the moment it was invoked. The only preview was `--dry-run`, a *separate*
invocation the README recommends but nothing enforces — and the README's own
warning ("don't blindly apply someone else's configuration") had no mechanism
behind it.

The same entry point is also the automation path: container builds, CI, `bash
-c` jobs and cron all call it, so any interactivity added must not be able to
hang a headless run. Bootstrap already runs unattended in bare containers
(single-user nix, `generic` host), which is the case a blocking prompt would
break most silently.

Two shapes were considered. A **per-step confirmation** (`y` / `n=skip` /
`a=all` / `q`) at each install and each privileged command was implemented
first and rejected in review: it interrupts a long run eight or more times,
tempts the user into `a` on the second prompt, and — because each answer is
local — never shows the total blast radius. The alternative is to describe
*everything* first and take one answer.

## Decision

> In the context of a bootstrap that installs software, uses root, and displaces
> existing files,
> facing the risk of an irreversible-feeling run started by accident and the
> requirement that automation stay unattended,
> we decided for one machine-wide **plan printed before the first mutation,
> cleared by a single yes/no**,
> and against per-step confirmations (and against relying on a separate
> `--dry-run` invocation),
> to achieve a visible blast radius at the one moment the user can still say no,
> accepting that every new install/privileged step must now also describe
> itself.

### The plan

Assembled in `platform/bootstrap.sh` after host selection and the privilege
gate, before any mutation, and printed by `print_plan` (`platform/lib.sh`) in
four buckets:

- **facts** — os/arch, flake host (+impure), privilege mode (`root`/`sudo`/
  `none`, with what that implies), network (upstream vs. the CN mirror set),
  whether nix is already present.
- **will install** — apt prerequisites, which nix flavour and from where
  (multi-user Lix vs. single-user `--no-daemon`), the Home Manager generation,
  the mise runtimes, Claude CLI + CodeGraph, and the resolved system components.
- **will write / link** — user and system `nix.conf` lines, the network-env
  marker, Home Manager symlinks, every link-map entry (`target -> source`), the
  login-shell change, the deferred Claude setup script.
- **will move your existing files aside** — printed **last and highlighted**,
  listing each of the user's real files that gets renamed (`*.backup`,
  `*.pre-dotfiles.bak`). This is a separate section on purpose: displacing
  existing data is the only genuinely alarming thing a bootstrap does, and as
  one dim line among fifty symlinks it is missed.

Steps needing root/sudo are tagged `[privileged]`.

### Ownership: every script describes its own steps

The plan must not become a hand-maintained second description that drifts from
the code. So the script that performs a step also describes it, and
`bootstrap.sh` merges:

| Producer | Contract |
|---|---|
| `lib.sh` `plan_fact`/`plan_install`/`plan_config`/`plan_backup` | in-process buckets; `plan_prereqs`/`plan_nix` sit beside `ensure_prereqs`/`install_lix` |
| `nix-cn.sh --plan` | emits `section<TAB>text<TAB>priv`; plan and apply share `conf_target`/`missing_lines` |
| `setup.py --plan-items` | same TSV for the post-HM half (link map, login shell, mise, Claude, system components) |

`plan_import_tsv` merges the TSV halves. `nix-cn.sh --plan` and `setup.py
--plan-items` are read-only by construction and are invoked with the *same
arguments* the real run will use, so plan and run cannot disagree. `setup.py`
runs its planner on a system `python3` (it is stdlib-only), which is why the
post-HM half can be described before Home Manager has provided `uv`.

### Clearance

`require_clearance` (`lib.sh`) and `Ctx.require_clearance`
(`installers/context.py`) ask exactly once. Yes proceeds; anything else — and
EOF, which is never read as consent — exits before the first change.

It asks **only when a human is there**: stdin is a tty, or stdin is a pipe but
`/dev/tty` is readable with stdout attached to it (the `curl … | bash` case,
where the answer is read from `/dev/tty` so it does not consume the piped
script). With no terminal it proceeds silently, so CI/containers behave exactly
as before. `--yes`/`-y`/`DF_ASSUME_YES=1` skips the prompt but still prints the
plan; `--dry-run` never asks (nothing to clear).

A yes exports `DF_ASSUME_YES=1`, which the nested `nix-cn.sh` and `setup.py`
inherit — that is how "one shot" holds across three processes. Run standalone,
`setup.py` prints its own half and takes its own clearance; `setup.py --plan`
prints it without running anything. The interactive pickers
(`nix_system_install.py`, `brew_cask_install.py`) already show a selection plus a
questionary confirm and are unchanged.

## Consequences

- The dangerous facts arrive when they are still actionable. `--dry-run` becomes
  an option rather than the only safety net, and the README's warning has a
  mechanism behind it.
- **New rule for contributors** (recorded in `AGENT.md`): a step that installs,
  uses privilege, or displaces a file must register a plan line next to the code
  that performs it. A step that runs without appearing in the plan silently
  defeats the clearance — this is the standing maintenance cost of this ADR.
- The plan is a *second* code path over the same decisions. Mitigated by sharing
  the read-only helpers (`missing_lines`, `_load_jsonc`, `OptionalComponent.
  resolve`) and by passing identical arguments, but a divergence is now possible
  in a way it was not before.
- Automation is untouched by design; the flip side is that the safety only
  exists where a tty does. A `bash -c` wrapper around bootstrap silently opts
  out.
- Plan fidelity is bounded in two places, both stated in the output rather than
  hidden: Home Manager symlinks are described as a set, not enumerated (a full
  list means building the activation package first — minutes of nix evaluation
  before the user has said yes), and with no system `python3` the post-HM half
  prints one line saying it could not be detailed.
- The mise runtime list is scraped from `home/mise.nix` with a regex, because
  mise is not on PATH yet at plan time. It degrades to naming the file if the
  `tools` block moves.
- `nix-cn.sh` was restructured (a `missing_lines` generator feeding both plan and
  apply). Behaviour is unchanged — verified line-for-line against the previous
  `--dry-run` output, CN and non-CN.
- The link-map lines follow ADR-0008/0009: they describe whatever mechanism is
  live. When ADR-0009 retires `apply_link_map`, those lines and the
  `.pre-dotfiles.bak` entries in the move-aside section go with it, leaving Home
  Manager's `.backup` as the only displacement to report.
