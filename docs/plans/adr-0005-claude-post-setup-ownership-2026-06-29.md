# ADR-0005: Claude config rebuilt by an install-driven post-setup

| Field | Value |
|---|---|
| Status | accepted |
| Date | 2026-06-29 |

## Context

`~/.claude` (and the sibling `~/.claude.json`) is a large, mixed tree: a little
real config (`settings.json`, `enabledPlugins`, the `agent-skillset`
marketplace) interleaved with a lot of per-machine runtime/account state
(credentials, caches, `projects/`, `sessions/`, `shell-snapshots/`, plugin git
checkouts). `.claude.json` in particular is opaque machine state (`machineID`,
`userID`, `oauthAccount`, onboarding flags) — nothing authored worth carrying.

Two models were considered:

1. **Symlink `~/.claude` → `<staging>/.claude`** so an accumulated copy travels
   between machines. Rejected: it drags opaque per-machine state across hosts,
   `.claude.json` doesn't make sense to share, and "which machine's state wins"
   becomes unclear.
2. **Install-driven** — treat the *setup* (plugins, MCP servers, agent tooling)
   as something reproducible by commands, and let each machine grow its own
   fresh runtime state. Chosen: the reproducible parts are few and well-known,
   and a fresh `.claude.json` per machine is strictly cleaner.

## Decision

### 1. The migration phase does not deploy Claude paths

`installers.components.CLAUDE_MANAGED_PATHS = (".claude", ".claude.json")`.
`migrate_dotfiles` passes it as `exclude` to both `link_dotfiles` and
`_staging_has_unlinked_items` (so an unlinked `.claude` doesn't trip the
container-restart "skip rsync" heuristic). The generic walk therefore never
symlinks staging's stale `.claude` state into `$HOME`; each machine starts with
whatever Claude Code creates fresh.

### 2. `ClaudeCode` rebuilds the config, in order

The `claude` optional component is multi-step. After installing the CLI it runs,
in order:

1. **Plugins** — `claude plugin marketplace add hernandor/agent-skillset`, then
   `claude plugin install <p>@agent-skillset --scope user` for each of
   `AGENT_SKILLSET_PLUGINS` (no bulk-install command exists yet).
2. **MCP via Smithery** — `npx -y @smithery/cli@latest install <pkg> --client
   claude` for `SMITHERY_MCP_SERVERS` (`@upstash/context7-mcp`,
   `@modelcontextprotocol/server-memory`).
3. **lark-cli** — `npx -y @larksuite/cli@latest install` (wires Lark's agent
   skills into Claude Code).
4. **codegraph** — reuse the standalone installer, then `codegraph install
   --target=claude --yes` (global agent wiring). `codegraph init` is per-project
   and is intentionally *not* run in a machine bootstrap.

All steps run through a shell that sources nvm and puts `~/.local/bin` on PATH
(`npx`, `claude`, `codegraph` are freshly installed this run and not on the
inherited PATH). Steps 1–4 use `check=False`: a Smithery key prompt or
interactive auth must not abort the bootstrap.

This runs in the optional phase — after migration and after the necessary Node
component provided `npx` — hence "post-setup".

## Consequences

- Each machine gets a fresh `~/.claude` / `~/.claude.json`; the setup is
  reproduced declaratively rather than carried as opaque state.
- Adding a plugin / MCP server / tool is an edit to the lists at the top of the
  module, not a manual per-machine step.
- Staging's old `.claude` / `.claude.json` become unused by deployment (left in
  place, not deleted).
- `settings.json` (model/theme/`includeCoAuthoredBy`) is **not** yet managed;
  `claude plugin install` writes `enabledPlugins`, but personal prefs currently
  fall back to defaults. Tracking those is a follow-up if wanted.
- Smithery server slugs and any required Smithery key are not verified at
  install time (steps are best-effort, `check=False`); confirm the memory-server
  slug and re-run if a step needs auth.
