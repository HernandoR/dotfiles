# platform/ — the imperative layer

Home Manager (the `flake.nix` + `home/`) owns the **user** environment
declaratively. This directory is the thin **imperative** layer for what Home
Manager cannot do on a non-NixOS host (ADR-0007): install nix, configure
mirrors, invoke Home Manager, set the login shell, and install Linux
system-level software.

## Entry point

```bash
./bootstrap.sh                     # auto-detect host; full bootstrap
./platform/bootstrap.sh --dry-run  # print every action without executing
./platform/bootstrap.sh --yes      # skip the clearance prompt (CI-style run)
./platform/bootstrap.sh --network CN            # enable China mirrors
./platform/bootstrap.sh --host dotfiles-debian  # pick a flake host explicitly
./platform/bootstrap.sh --system docker,cuda    # + Linux system components
./platform/bootstrap.sh --agents claude         # only Claude Code (default: claude,codex,pi)
./platform/bootstrap.sh --agents none           # no agent tooling (was --no-claude)
```

## Plan + clearance (ADR-0010)

On an interactive terminal nothing is touched until the whole plan has been
printed and cleared **once** — installs, the network/mirrors in use, the config
files written and the symlinks placed, with `[privileged]` on the steps that use
root/sudo, and a final highlighted section listing every existing file that gets
moved aside (`*.backup`). There are deliberately no
per-step prompts.

Each script describes its own steps so the plan cannot drift from the run:

| Producer | Emits |
|---|---|
| `lib.sh` `plan_fact`/`plan_install`/`plan_config`/`plan_backup` | facts + the pre-HM shell steps (`plan_prereqs`, `plan_nix`) |
| `nix-cn.sh --plan` | `section<TAB>text<TAB>priv` for the network marker + system `nix.conf` |
| `setup.py --plan-items` | the same TSV for the post-HM half (login shell, mise, the coding agents, system components) |

`bootstrap.sh` merges them with `plan_import_tsv`, prints with `print_plan`, and
calls `require_clearance`. No terminal (CI, container, cron) or `--yes` /
`DF_ASSUME_YES=1` or `--dry-run` → no prompt. A yes exports `DF_ASSUME_YES=1`, so
`setup.py` (which asks for its own clearance when run standalone) does not ask
twice. `setup.py --plan` prints the post-HM half on its own.

`bootstrap.sh` runs, in order: prerequisites → install Lix → configure nix
(flakes; CERNET mirror only when `DOTFILE_NETWORK_ENV=CN`) → `home-manager
switch -b backup` (which also places the ADR-0009 Tier-B out-of-store links from
`home/env-links.nix`) → login shell → the coding-agent toolchain → optional system
components.

## Files

| File | Role |
|---|---|
| `bootstrap.sh` | orchestrator / entry point (pre-HM shell half) |
| `lib.sh` | shared helpers (OS/host detection, Lix install, plan + clearance) |
| `nix-cn.sh` | flakes + CN mirror gating (system nix.conf, sudo) + persist `~/.config/dotfiles/network-env` |
| `setup.py` | post-HM half: `chsh` → mise runtimes → coding agents → system components |
| `installers/agents.py` | ADR-0011: the capability manifest (marketplaces, plugins, MCP servers, pi packages) + one `Agent` class per agent that projects it with that agent's own CLI |
| `installers/components.py` | the `OptionalComponent` registry (docker, cuda, nvidia, llvm, brew) + CodeGraph |
| `installers/managers.py` | install backends (`apt`, `brew`, `scripts`) and their specs |
| `installers/context.py` | `Ctx`: privilege detection, `run_command`, dry-run, clearance |

## The agent toolchain (ADR-0011)

`setup_agents` installs the selected agents and projects the manifest in
`installers/agents.py` onto each with that agent's own CLI. All of it is
non-interactive and runs on every bootstrap — a single source that needs a human to
apply is not a single source. What lands where:

| Plane | Where it lives | How it is applied |
|---|---|---|
| instruction | `~/.agents/AGENTS.md` (the only source) | `~/.codex/AGENTS.md` + `~/.pi/agent/AGENTS.md` symlinks; `@~/.agents/AGENTS.md` import in the thin `~/.claude/CLAUDE.md` shell |
| capability | `MARKETPLACES` / `PLUGINS` / `MCP_SERVERS` / `PI_PACKAGES` | `claude plugin …` + `codex plugin …` (both have marketplaces), `claude mcp add`, `codex mcp add`, `pi install`, and `~/.agents/mcp.json` for pi's MCP (it has no MCP CLI) |
| preference | each agent's own config | **never touched** — all three rewrite it at runtime |

Loose skills live in `~/.agents/skills` (Codex reads it natively; `~/.codex/skills`
and `~/.pi/agent/skills` link to it). Links are re-asserted after any delegated
installer (`codegraph`) that appends to a linked file and writes it back. agentmemory is wired to pi + Codex only and
its daemon is the Home Manager unit in `home/agentmemory.nix`, started here once
the binary exists. Select agents with `--agents` (`claude,codex,pi` / `all` /
`none`) or `DOTFILE_AGENTS`. Projection is **add-only**: dropping an entry from the
manifest does not uninstall it from a machine that already applied it.

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
