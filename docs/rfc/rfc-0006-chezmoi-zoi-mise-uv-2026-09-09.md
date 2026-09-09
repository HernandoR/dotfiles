# RFC-0006: Leave Nix + Home Manager for chezmoi + zoi + mise + `uv run` scripts

| Field | Value |
| --- | --- |
| Status | Resolved |
| Date | 2026-09-09 |
| Outcome | [ADR-0013](../plans/adr-0013-chezmoi-zoi-mise-uv-2026-09-09.md) |

## Problem

ADR-0007 put the whole user environment behind a Nix flake and standalone Home
Manager on Lix. Fourteen months in, the cost side of that decision dominates:

- **Every host pays the Nix tax.** A first bootstrap needs root to install a
  daemon (or a single-user store with its `nixbld`, `/homeless-shelter` and
  stack-limit workarounds — `platform/bootstrap.py` grew four repair functions
  for them), pulls a multi-GB closure, and evaluates a flake before a single
  dotfile lands. On CN networks that meant substituter wiring and flake-input
  seeding just to get `ripgrep`.
- **The mutable half fought the model.** ADR-0009 had to invent Tier B — out-of-
  store links with seed/repair activation hooks — because a store symlink cannot
  be rewritten by the tool that owns the file. Roughly half of `home/` was
  machinery for escaping Home Manager rather than using it.
- **Per-environment deltas needed branches.** `prod/mewtant` and
  `prod/ec2-wo-fsx` existed only to carry one file (`home/env-branch.nix`),
  with a rebase discipline documented in AGENTS.md so they would not conflict.
- **Two evaluation languages.** Nix for the declarative half, Python for the
  imperative one; a change to the agent toolchain touched both.

The owner asked for a switch to **chezmoi** (dotfiles), **zoi** (packages),
**uv** (Python) and **mise** (runtimes), keeping the Python where it earns its
place as `uv run` scripts.

## Options considered

1. **Stay, and slim Home Manager** — keep Nix for packages, move dotfiles to
   plain files. Rejected: the bootstrap cost is the Nix install itself, not the
   module count.
2. **chezmoi for everything, with `run_` scripts in shell** — rejected: the
   agent manifest (`agents.py`, 2k lines of reviewed logic) and the plan-first
   clearance (ADR-0010) are Python and worth keeping verbatim.
3. **chezmoi + zoi + mise, Python retained as `uv run` scripts** — chosen.
   chezmoi owns the files and machine data; the env links, package install,
   post-apply setup and bootstrap are PEP 723 scripts chezmoi invokes.

## Findings that shaped the outcome

- **zoi's registry is small.** On 2026-09-09, with `core`, `main`, `extra`,
  `community` and `test` enabled, `zoi list --all` showed nine packages, none of
  them in this repo's toolset. zoi accepts native specs (`brew:jq`, `apt:jq`,
  `native:jq`) and the docs describe 40+ external managers, but a real run of
  `zoi install --yes brew:cowsay` printed `Success` and installed nothing
  (`brew list` unchanged, `zoi list` empty). So zoi is adopted as the **front
  door** and `scripts/packages.py` verifies every binary afterwards, falling
  back to the native manager and then to mise. When zoi's passthrough matures,
  the fallback simply stops firing.
- **chezmoi's `create_` prefix is Tier B's seed semantics** for a single file,
  but it cannot put the file on a persistent volume. The env links therefore
  stay a script (`scripts/env_links.py`) fed by `home/.chezmoidata/envlinks.toml`
  — and they are deliberately *not* chezmoi source entries, so `chezmoi apply`
  can never replace one with a regular file.
- **`chezmoi init` prompts replace the `prod/*` branches.** `env`, `stateRoot`,
  `network`, `agents` and `system` are answered once per machine (env vars win
  for unattended runs) and drive the templates and the scripts. Both prod
  branches collapse to `--env mewtant` / `--env ec2-wo-fsx`.
- **`.chezmoiroot`** lets the source tree live in `home/` while `scripts/`,
  `docs/` and the Justfile stay at the repo root, and pinning `sourceDir` to the
  clone in the generated config keeps a single checkout as the source of truth.

## Resolution

Adopted as ADR-0013. The Nix generation of the repo is preserved on
`archive/homemanager/main`, `archive/homemanager/prod/mewtant` and
`archive/homemanager/prod/ec2-wo-fsx`.
