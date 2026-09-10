# AGENTS.md

Cross-platform **dotfiles**: **chezmoi** owns the files (`home/`, the source
state), **mise** the runtimes and most of the CLI toolset, **nvm** the Node
ecosystem, and a set of **`uv run` Python scripts** (`scripts/`) does everything
imperative — the bootstrap, the persistent `$HOME` links, the OS-level packages,
the agent toolchain.
[README.md](README.md) is the full manual — layout, commands, conventions,
guardrails, and how to add anything.

The rules an agent must not learn the hard way:

- **Design lives in ADRs/RFCs.** `docs/plans/` (ADRs) records settled intent,
  `docs/rfc/` the discussion trail; both have indexes. Read the governing ADR
  before reshaping what it governs — ADR-0013 owns the layout and the ownership
  rule, 0010 plan-first clearance, 0011/0012 the agent toolchain. ADRs 0001–0009
  are history (the Nix generation, on `archive/homemanager/*`). New design
  directions start as an RFC, decisions land as an ADR.
- **Use `just`.** Prefer a recipe (`just apply` / `diff` / `status` / `check` /
  `plan`) over remembering the raw command. `just` lists them all.
- **Data over code.** A tool or runtime goes in `home/.chezmoidata/mise.toml`
  whenever mise has a backend for it (check `mise registry`); Node packages in
  `node.toml` (nvm, never mise); only OS-level packages in `packages.toml`; a
  persistent `$HOME` path in `envlinks.toml`. The scripts read those files; do
  not hardcode an inventory in a script.
- **Machine differences are chezmoi data, not branches.** `env`, `stateRoot`,
  `network`, `agents`, `system` are answered at `chezmoi init` (or via
  `DOTFILE_*` env vars). Gate an environment-only thing with `envs = [...]` in
  `envlinks.toml` or a template condition. `main` is the only branch.
- **A file a tool rewrites at runtime is never a chezmoi source entry.** It is
  an env-link entry (seeded once, then the tool's). Agent configs, mise's
  `config.toml`, `~/.claude.json` are the standing examples.
- **Nothing is installed by hand on a machine** — packages, runtimes and agent
  capabilities all go through their files in this repo (README: *Adding
  software*, *Coding agents*).
- **Cite `file:line`** for claims about structure or conventions.
- **Never block on a prompt.** Everything is unattended by default: a new step
  must run to completion with no human, using the installer's non-interactive
  flag and `stdin_devnull=True` for list-driven commands. Being asked is opt-in
  (`--interactive` / `DOTFILE_INTERACTIVE=1`); what truly needs a human goes to
  the deferred post-login script.
- **No test framework.** Verify with `just check` (data + scripts + a full
  render per environment) and `./bootstrap.sh --dry-run --verbose`.
- **Commits:** Conventional-Commits `type(scope): subject`, in English.

Before touching `home/dot_zshrc.tmpl` (plugin load order), the env-link
inventory, agent config files or the CN mirror gating, read the guardrails:
[README — Don't touch / be careful with](README.md#dont-touch--be-careful-with).
