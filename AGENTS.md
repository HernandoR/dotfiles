# AGENTS.md

Cross-platform **dotfiles**: a **Nix flake + standalone Home Manager** on
[Lix](https://lix.systems/) owns the user environment declaratively (`home/`),
and a thin **Python-first imperative layer** (`platform/`, launched by the
shell-only `bootstrap.sh`) handles what Home Manager cannot on a non-NixOS host.
[README.md](README.md) is the full manual — layout, commands, component model,
conventions, guardrails, and how to add anything.

The rules an agent must not learn the hard way:

- **Design lives in ADRs/RFCs.** `docs/plans/` (ADRs) records settled intent,
  `docs/rfc/` the discussion trail; both have indexes. Read the governing ADR
  before reshaping what it governs — ADR-0007 owns the two layers, 0009 config
  ownership, 0010 plan-first clearance, 0011/0012 the agent toolchain. New
  design directions start as an RFC, decisions land as an ADR.
- **Use `just`.** The Justfile carries host resolution and the `-b backup`
  policy; prefer a recipe (`just build` / `diff` / `switch` / `check` / `plan`)
  over remembering the raw command. `just` lists them all.
- **Keep the layers separate.** Declarative intent goes in `home/`; the
  imperative remainder in `platform/`. Nothing user-level is installed
  imperatively, and no agent capability is installed by hand on a machine —
  both go through their files in this repo (README: *Adding software*,
  *Contributing*).
- **Every `prod/*` branch carries only the minimal delta against `main`.**
  Env-specific state belongs in `home/env-branch.nix` — the ONLY file an env
  branch edits, so its rebases replay cleanly. Anything useful to every
  environment goes to `main` first.
- **Cite `file:line`** for claims about structure or conventions.
- **No test framework.** Verify with `./bootstrap.sh --dry-run --verbose`,
  `nix flake check`, and container runs (RFC-0001).
- **Commits:** Conventional-Commits `type(scope): subject`, in English.

Before touching `home/shell.nix` (fzf-tab order), `home.stateVersion`, agent
config files, or mirror wiring, read the guardrails:
[README — Don't touch / be careful with](README.md#dont-touch--be-careful-with).
