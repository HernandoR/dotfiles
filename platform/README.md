# platform/ — the imperative layer

Home Manager (the `flake.nix` + `home/`) owns the **user** environment
declaratively. This directory is the thin **imperative** layer for what Home
Manager cannot do on a non-NixOS host (ADR-0007): install nix, configure
mirrors, invoke Home Manager, set the login shell, and install Linux
system-level software.

## Entry point

The layer is **Python-first**: `bootstrap.sh` (repo root) is the only shell in
the bootstrap, and its only job is to guarantee a `python3` (installing one with
the native package manager when a bare container lacks it) and exec
`platform/bootstrap.py`, which owns everything else — the plan, the clearance,
prereqs, Lix, nix config, the Home Manager switch, and the post-HM steps
(imported from `setup.py` and run in the same process).

```bash
./bootstrap.sh                     # auto-detect host; full bootstrap
./bootstrap.sh --dry-run           # print every action without executing
./bootstrap.sh --yes               # skip the clearance prompt (CI-style run)
./bootstrap.sh --network CN             # enable China mirrors
./bootstrap.sh --host dotfiles-debian   # pick a flake host explicitly
./bootstrap.sh --system docker,cuda     # + Linux system components
./bootstrap.sh --agents claude          # only Claude Code (default: claude,codex,pi)
./bootstrap.sh --agents none            # no agent tooling (was --no-claude)
```

## Plan + clearance (ADR-0010)

On an interactive terminal nothing is touched until the whole plan has been
printed and cleared **once** — installs, the network/mirrors in use, the config
files written and the symlinks placed, with `[privileged]` on the steps that use
root/sudo, and a final highlighted section listing every existing file that gets
moved aside (`*.backup`). There are deliberately no
per-step prompts.

Each step registers what it *would* do before anything runs, so the plan cannot
drift from the run: the pre-HM planners (`plan_prereqs`, `plan_nix`,
`plan_nix_config`) live next to the code that performs them in `bootstrap.py`,
and the post-HM half comes from `setup.build_plan()` — the same function a
standalone `setup.py --plan` prints. `bootstrap.py` merges both halves into one
`Plan`, renders it, and calls `require_clearance`. No terminal (CI, container,
cron) or `--yes` / `DF_ASSUME_YES=1` or `--dry-run` → no prompt. A yes sets
`assume_yes` on the shared `Ctx` and exports `DF_ASSUME_YES=1`, so nothing asks
twice.

`bootstrap.py` runs, in order: prerequisites → install Lix → configure nix
(flakes; CERNET mirror only when `DOTFILE_NETWORK_ENV=CN`) → `home-manager
switch -b backup` (which also places the ADR-0009 Tier-B out-of-store links from
`home/env-links.nix`) → login shell → the coding-agent toolchain → optional system
components.

## Files

| File | Role |
| --- | --- |
| `../bootstrap.sh` | the only shell: ensure `python3`, exec `bootstrap.py` |
| `bootstrap.py` | the orchestrator — plan + clearance, prereqs, Lix, nix config (+CN), HM switch, then the post-HM steps in-process |
| `setup.py` | the post-HM steps (`chsh` → mise runtimes → coding agents → system components); also runnable standalone via `uv run` |
| `installers/agents.py` | ADR-0011: the capability manifest (marketplaces, plugins, MCP servers, pi extensions) + one `Agent` class per agent; Claude/Codex project through their own CLIs, pi through declarative files this repo owns (ADR-0012) |
| `installers/components.py` | the `OptionalComponent` registry (docker, cuda, nvidia, llvm, brew) + CodeGraph |
| `installers/managers.py` | install backends (`apt`, `dnf`, `zypper`, `pacman`, `apk`, `brew`, `scripts`), keyed by OS family, and their specs |
| `installers/context.py` | `Ctx`: privilege detection, `run_command`, dry-run, clearance |

## The agent toolchain (ADR-0011 + ADR-0012)

`setup_agents` installs the selected agents and projects the manifest in
`installers/agents.py` onto each. All of it is non-interactive and runs on every
bootstrap — a single source that needs a human to apply is not a single source.
Install channels: claude and codex keep their own official installers; pi is a
mise npm tool (`home/mise.nix`). pi's config root `~/.pi/agent` is a Tier-B
out-of-store env link (ADR-0009), and its `settings.json` is **seeded, never
owned** (ADR-0012): the `packages` array is reconciled to the manifest, every
other key is written only when absent, so `/model`, `/theme` and hand edits
survive re-projection. What lands where:

| Plane | Where it lives | How it is applied |
| --- | --- | --- |
| instruction | `~/.agents/AGENTS.md` (the only source) | `~/.codex/AGENTS.md` + `~/.pi/agent/AGENTS.md` symlinks; `@~/.agents/AGENTS.md` import in the thin `~/.claude/CLAUDE.md` shell |
| capability | `MARKETPLACES` / `PLUGINS` / `MCP_SERVERS` / `PI_PACKAGES` | `claude plugin …` + `codex plugin …` (both have marketplaces), `claude mcp add` + `codex mcp add`; pi has no MCP or marketplace CLI, so it gets three declarative files this repo owns: `~/.agents/mcp.json`, `~/.pi/agent/claude-plugins.json`, and the `packages` array in its settings |
| preference | each agent's own config | never overwritten — Claude's and Codex's are never written from `platform/` at all; pi's is seeded leaf-by-leaf, only where a key is absent (ADR-0012) |

Loose skills live in `~/.agents/skills` (Codex and pi read it natively;
`~/.codex/skills` and `~/.pi/agent/skills` link to it); marketplace-managed
skills reach pi through `pi-claude-marketplace`, an independent marketplace
client that clones from git itself. Links are re-asserted after any delegated
installer (`codegraph`) that appends to a linked file and writes it back.
Memory is **two layers**: the shared MCP knowledge graph at
`~/.agents/memory/memory.jsonl` (declared once in `MCP_SERVERS`, reaching all
three agents — no service, no credential, no egress), and `pi-memory` for pi
alone. Claude's built-in memory stays off by the owner's decision — preference
plane, never projected from here.
Select agents with `--agents` (`claude,codex,pi` / `all` / `none`) or
`DOTFILE_AGENTS`. Projection is **add-only**: dropping a manifest entry does not
uninstall it from a machine that already applied it — except the names listed in
`RETIRED_MCP_SERVERS` / `RETIRED_PI_PACKAGES`, which the files this repo writes
whole do drop (a retired server could otherwise never leave a host).

## Post-login setup (Smithery + Lark)

What genuinely blocks on a human is *written* to
`~/.local/share/dotfiles/post-login-setup.sh` instead of being run. The user
invokes it once via the `dotfiles-postsetup` zsh function; it self-removes on
success, and every step is `|| true` so nothing aborts the rest. What it asks:

1. **Smithery auth** — the [Smithery](https://smithery.ai/) CLI is a mise npm tool
   (`npm:@smithery/cli`), materialized eagerly by `setup_runtimes`, so it is called
   directly (no `npx`). With `SMITHERY_API_KEY` in the environment it offers to
   verify that key (`smithery auth whoami`); without one it offers an interactive
   `smithery auth login`.
2. **Smithery namespace** — offers to add your namespace's aggregated MCP endpoint
   (`https://mcp.smithery.run/<namespace>`) to Claude via
   `smithery mcp add … --client claude`, falling back to
   `claude mcp add --transport http …`. A commented-out
   `smithery mcp add <server>` line (e.g. `upstash/context7-mcp`, already covered
   by the namespace) is left as a template for adding a single server later.
3. **Lark CLI** — `npx -y @larksuite/cli@latest install` (node from mise); its
   skills land in the shared `~/.agents/skills` root.

The namespace endpoint is here rather than in `MCP_SERVERS` because its name comes
from the logged-in Smithery account, not from the repo. Note that `setup.py`
rewrites this script on **every** run, so a re-bootstrap offers it again even after
you completed it; `--agents none` skips this half entirely.

## What is NOT here (owned by Home Manager)

Shell (zsh + starship + fzf + fzf-tab), git, tmux, the CLI toolset
(fd/ripgrep/gh/jj/bottom/mergiraf/difftastic/…), language runtimes (mise:
node/rust; uv: python), and all dotfiles. Edit `home/` for those.

## CN mirrors

A single switch — `DOTFILE_NETWORK_ENV=CN` — gates every China mirror. When set:
the CERNET nix substituter is written to the system nix.conf (so the daemon
serves it to all users), and the pypi/uv + rustup mirror vars are exported by the
Home Manager `.zshenv`. When unset, upstream defaults are used everywhere.
