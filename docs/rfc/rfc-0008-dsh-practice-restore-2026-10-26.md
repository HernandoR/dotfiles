# RFC-0008: Restore the owner's DeepSeek Harness practice from the repo

| Field | Value |
| --- | --- |
| Status | Resolved |
| Date | 2026-10-26 |
| Outcome | [ADR-0014](../plans/adr-0014-dsh-practice-restore-2026-10-26.md) |

## Summary

A fresh machine today gets every coding agent **except the owner's primary
harness**. DSH is installed by hand, signed in by hand and configured through its
Settings UI, so the desktop profile's plugin set, the model / provider /
web-search capability and the nowledge-mem MCP server exist only on the live
machine. This RFC records the restore path the owner approved: the official
Homebrew cask, the CLI linked out of the app bundle, one reviewed inventory
(`home/.chezmoidata/dsh.toml`), and a new `scripts/dsh.py` that generates exactly
the two files under `$DSH_HOME` the app itself never writes. Secrets stay
machine-local and manual, by nature.

The outcome is [ADR-0014](../plans/adr-0014-dsh-practice-restore-2026-10-26.md);
this document is the discussion trail behind it.

## Motivation

### The one agent with no restore path

[README — Coding agents](../../README.md#coding-agents) says DSH "needs no
entry in that manifest", and that is correct for ADR-0011's plane ②: DSH reads
`~/.agents/AGENTS.md` and `~/.agents/skills` directly, so instruction and loose
skills arrive with the state root. What that sentence does not cover is the
harness's own machine-wide state, and there is a lot of it. Measured on the
reference host, 2026-10-26:

- `~/.dsh/profiles/desktop/package.json` declares **13 ordered bundles** (seven
  shipped `@deepseek-ai/*` bundles plus six marketplace plugins at exact
  versions: `@changfenhuang/dsh-genui` 0.14.0, `@linxin666/dsh-remote-web-ui`
  0.4.8, `@wxg-prc-cpg/browser-skill-dsh-plugin` 0.3.3, `dsh-better-sidebar`
  0.28.0, `dsh-context` 0.75.1, `dshmarket` 1.70.2).
- The app-owned profile patch carries the owner's working defaults: provider
  `opencode`, model `deepseek-v4.1-flash` at `high` reasoning effort, an
  `OPENCODE_API_KEY` provider binding, a seven-model subagent allowlist, and
  DeepSeek's own search/fetch providers.
- The nowledge-mem MCP server is a root `insert:` row — server name
  `nowledge_mem` over streamable HTTP, with per-tooling headers.

None of it is in the repo; a fresh machine gets a working harness with none of
the owner's capability. Worse, the live profile patch stores the MCP bearer
**literally** in an app-written file. That is the state the repo has to replace,
and it is also the strongest argument for a *generated* file rather than a
committed one.

`README — Don't touch / be careful with` already forbids the obvious shortcut:
`~/.dsh/` is a file a tool rewrites at runtime, so it may never be a chezmoi
source entry. The restore path therefore needs a writer outside chezmoi's source
tree.

### What the app actually owns

The config model decided the mechanism. `$DSH_HOME` (default `~/.dsh`) holds one
directory per profile plus runtime state:

| Path | Written by | Role |
| --- | --- | --- |
| `profiles/<name>/cordis.yml` | the app, on every boot | the generated composition; editing it is pointless |
| `profiles/<name>/cordis.patch.yml` | the app (Settings UI, dshmarket) | that profile's own patch layer |
| `profiles/<name>/package.json`, `pnpm-workspace.yaml` | `dsh plugin` (pnpm) | installed bundles and the pnpm settings that install them |
| `$DSH_HOME/cordis.patch.yml` | **nothing** — the app never writes it | the machine-wide "home patch" |
| `$DSH_HOME/.env` | (this repo, under ADR-0014) | feeds `process.env` at boot |
| `.credentials.yaml` (0600), `sessions/`, `storages/`, `cache/` | the app | runtime state; must never be persisted |
| `profiles/<name>/node_modules/`, `.dsh-market/` | pnpm / the app | caches |

Three properties of that table matter:

- **The profile patch is app-owned.** Settings and the marketplace write it, so
  a seed would be fought over and a merge would need a YAML parser this repo
  does not have (conventions: PEP 723, stdlib only).
- **The home patch is the one composition point the app never writes.** In the
  bundled boot code (`dsh-app-boot/lib/index.js`, `readProfilePatches`) the
  ordered list is: bundle patches, then the profile patch, then
  `$DSH_HOME/cordis.patch.yml`, then CLI overlays. It is machine-wide, so every
  profile — `desktop`, `web`, `tui` — composes it.
- **`!!js` is supported in the patch dialect**, and
  `loadLayeredEnv` applies `$DSH_HOME/.env` only where the inherited process
  environment leaves a name unset. A secret can therefore reach the composed
  tree without ever being written into a file that travels with the repo.

### The bundle is the only CLI

The desktop cask has no CLI artifact. The `dsh` command ships **inside**
the app: `Contents/Resources/runtime/cli/bin/dsh` is a short POSIX-sh launcher
that resolves the bundle and execs Electron as Node against
`app.asar/dsh/node_modules/@deepseek-ai/dsh-desktop-host/lib/cli.js`. The app's
own "Manage dsh command" writes to `/usr/local/bin` and needs admin, so the
repo should link `~/.local/bin/dsh` into the bundle instead.

Likewise the cask itself is the right install channel and there is no other: it
is `homebrew/cask` (`auto_updates=true`, arm64, macOS ≥ 13, `uninstall` quits
`com.deepseek.dsh`), and its `zap` list trashes `~/.dsh` — so
`brew uninstall --zap deepseek-harness` is destructive and must stay forbidden.

### Two constraints that shaped the alternative set

- **No YAML parser.** The repo is stdlib-only; merging an app-owned YAML file
  correctly (preserving comments, ordering, unknown keys) is out of scope. The
  repo can only *author* a whole file the app composes.
- **No writes while the app runs.** The desktop app probes a singleton lock at
  `~/Library/Application Support/@deepseek-ai/dsh-desktop/SingletonLock`; the
  plugin manager takes `profiles/desktop/package.json.lock`, which a running app
  does not hold, so that lock is not mutual exclusion. The step has to detect
  the app and skip rather than race it.

## Goals

- A freshly installed macOS machine gets the owner's DSH back from the repo plus
  machine-local secrets: the app, the `dsh` CLI, the desktop profile's plugin
  set, and the capabilities above.
- One reviewed inventory for it (`home/.chezmoidata/dsh.toml`), read by the
  script; no inventory restated in code.
- No secret in git, in the generated patch, or in any file the repo owns.
- The step runs in the apply path, unattended, and is idempotent.
- The app keeps ownership of everything it writes: the script writes only what
  the app never writes.

## Non-Goals

- **Sessions, reminders, history, attachments, browser-extension state,
  keybindings and dshmarket state.** They are runtime state; the env-link
  treatment for `~/.dsh` is explicitly deferred (see Open Questions).
- **Application preferences and onboarding.** `ui-chat`, `ui-settings`,
  `ui-settings-account` and `better-sidebar`'s config rows stay with the
  Settings UI; only capability is restored.
- **Pinning the app version.** The cask self-updates; a major update may need a
  re-run, not a pinned download.
- **The DeepSeek account sign-in and the OAuth device flow**, and
  `~/.dsh/.credentials.yaml`. Never provisioned.
- **The shared `~/.agents` root.** Owned by ADR-0011/ADR-0012 and out of scope.
- **A Linux desktop app.** The cask is macOS-only by design; Linux hosts are
  headless and skip the step.

## Proposal

1. **Install the app as one cask entry.** `packages.toml` gains
   `deepseek-harness` with `cask = true`, `only = "darwin"` and
   `probe_darwin = ["/Applications/DeepSeek Harness.app"]`. A GUI `.app` has no
   mise backend, and `scripts/packages.py` already knows how to install casks
   (`packages.py:86-87`), so this reuses the existing channel.

2. **Link the CLI out of the bundle, with an OS gate.** `envlinks.toml` gains
   `.local/bin/dsh` → the bundle launcher. It needs a new generic
   `only = "darwin" | "linux"` gate on both entries and plain links — same ids
   as `packages.toml` — implemented in `scripts/env_links.py` and validated by
   `scripts/check.py`, so a headless Linux host never gets a link that could
   only dangle.

3. **Put the capability in one inventory.** `home/.chezmoidata/dsh.toml`
   declares the desktop profile's ordered bundles and exact plugin versions, the
   pnpm workspace settings, the patch rows (default model, provider binding,
   subagent allowlist, web providers), the token-gated MCP server, and the
   secret **names** (never values).

4. **Generate the two files the app never writes.** A new `scripts/dsh.py`
   renders `$DSH_HOME/cordis.patch.yml` (home patch) and `$DSH_HOME/.env`
   (0600). Secrets are read from the process environment — in practice
   `~/.exports.local` through the login shell — and written only to `.env`, so a
   GUI-launched app that did not inherit the shell still resolves them. The
   generated patch carries a `!!js` expression — one single-quoted scalar — that
   reads the variable from `process.env`, so no secret is ever written into the
   patch or the repo. `--print-patch` prints the generated patch for the
   assertion below.

5. **Seed the profile, then let the app install its own plugins.**
   `dsh.py` seeds `profiles/desktop/package.json` **add-only** (plugin entries
   and the ordered bundle list) and seeds `pnpm-workspace.yaml` only when
   missing, then runs `dsh plugin --profile desktop install`. Pre-seeding the
   manifest is what makes a first bootstrap work: `dsh plugin` cannot
   materialize a profile that does not exist yet, but it accepts a
   pre-seeded one, and it materializes ~25 s unattended. If the app was launched
   first, it created the profile from the shipped web template and the add-only
   merge lands on top.

6. **What is restored is capability, not preference.**

   | Restored | Detail |
   | --- | --- |
   | Plugin bundles | 13, in order, with six marketplace packages pinned to exact versions |
   | pnpm workspace | `allowBuilds`, `minimumReleaseAgeExclude` — without them the native pieces do not build |
   | Default model | provider `opencode`, model, reasoning effort |
   | Provider binding | `opencode` with `apiKeyEnv: OPENCODE_API_KEY` |
   | Subagent allowlist | the seven models the owner uses |
   | Web access | `searchProvider`, `fetchProvider` |
   | nowledge-mem MCP | `serverName nowledge_mem`, streamable HTTP, bearer by env reference |

   Deliberately not restored: the four app-owned preference rows listed under
   Non-Goals. Their bundles still load with app defaults.

7. **Wire it into the apply path, not the post-login script.**
   `home/.chezmoiscripts/run_onchange_after_28-dsh.sh.tmpl` (hash-keyed on
   `dsh.toml` + `dsh.py`, darwin-gated) runs it after the packages step that
   installed the bundle; `just dsh` re-runs it by hand. The only manual part is
   adding secrets, which is opt-in by nature — nothing here waits on a human.

8. **Never touch what the app writes.** The script refuses to write
   `cordis.yml`, the profile patch, `node_modules` or `.credentials.yaml`, and
   skips all writes and the plugin install while the app is running (singleton
   lock detected → warn and exit 0).

## Alternatives Considered

| Alternative | Why not |
| --- | --- |
| Manage `$DSH_HOME/cordis.patch.yml` as a chezmoi source entry | It would need chezmoi-rendered secrets (putting them in a templated source file) or a token-less MCP server that YAML cannot conditionally omit. Script generation keeps the file secret-free and repo-free, and lets `check.py` assert both. |
| Seed the app-owned `profiles/desktop/cordis.patch.yml` textually | The repo has no YAML parser (stdlib only), the app rewrites and renames that file, and Settings would fight the seed every time it saves. |
| Add a `DshAgent` subclass to `scripts/agents.py` | ADR-0011's 2026-10-23 entry records why DSH is not an `Agent` subclass: it reads `~/.agents` directly, an `all` default selection would try to install a macOS `.app` on Linux CI, and its MCP surface here is one machine-level server, not the shared `MCP_SERVERS` projection. |
| Download the nightly feed ZIP instead of the cask | The feed publishes `nightly-mac.yml` and a sha512'd ZIP, so it works as a fallback when brew is blocked — but it is not official packaging, and the cask is signed, self-updating and already the repo's channel for GUI apps. |
| Env-link `~/.dsh` onto the state root, like `~/.claude` | A v1 non-goal: it would move a live `~/.dsh` out from under a running app, and `~/.dsh` is runtime state plus a generated config, not the repo's config. Worth a follow-up with a `preserve_dir`-style migration. |
| Do nothing; document "install DSH by hand, configure it in Settings" | That is today's state, and it is exactly the gap this RFC exists to close: the owner's practice is not reconstructible from memory. |

## Risks

- **The home patch is machine-wide.** `web` and `tui` profiles also receive the
  providers, the MCP server and the default model. That is the design (one
  place to pin capability), but it is a behaviour change for profiles that were
  previously left alone.
- **Pinned rows become repo-owned.** The Settings UI will show those entries as
  overridden by a home patch, and saving them there will not stick. The in-chat
  model picker still works per session; only saving a new default no-ops.
- **A major app self-update can outrun the pinned plugin versions.** The step
  may need a re-run, or `dsh plugin allow-version` for a bundle whose peer range
  moved.
- **Homebrew's local index can be stale.** On the reference host the cask is
  present in the app bundle but the local index answers `No Cask with this name
  exists`; the formulae.brew.sh API is authoritative. A stale index must be
  diagnosed as an index problem, not a missing cask.
- **`brew uninstall --zap` is destructive.** The cask's zap list trashes
  `~/.dsh`; the README guardrail has to keep saying so.
- **Skipping while the app runs leaves the restore stale** until the next apply.
  Correct behaviour (never race the app), but it needs to be visible in output.
- **Secrets are manual.** Without `NMEM_API_KEY` the token-gated MCP server is
  omitted from the generated patch (with a warning naming it); without
  `OPENCODE_API_KEY` the provider is declared but cannot authenticate. The
  remedy is adding the secret and re-running `just dsh`, not a failed apply.
- **Linux is a no-op.** Only the darwin-gated cask and link exist, so a Linux
  host records "skip" and gets no harness — intended, but it belongs in the ADR.

## Open Questions

Deliberately left open; none blocks v1.

1. **Does `~/.dsh` join `envlinks.toml` in a later change?** That would give
   sessions and history a persistent volume, but it needs a migration for a live
   app directory and an ownership split from the two generated files.
2. **Can a major app update be detected and repaired automatically?** Today it
   is a re-run plus `dsh plugin allow-version`; a version probe in `dsh.py`
   could name the drift instead of relying on the user noticing.

## Acceptance Criteria

Criteria as written; the second through seventh were exercised on 2026-10-26
against a scratch `DSH_HOME` and a real DSH boot, the first awaits a clean host.

- [ ] On a clean macOS host, `just apply` installs the cask, places
      `~/.local/bin/dsh` into the bundle, and writes
      `$DSH_HOME/cordis.patch.yml` plus a 0600 `$DSH_HOME/.env`.
- [ ] `DSH_HOME=$(mktemp -d) just dsh` materializes all 13 bundles (a real
      `node_modules`), and `DSH_HOME=<that dir> dsh --profile web --dump-config`
      exits 0 with the generated home patch composing.
- [ ] `just dsh --print-patch` contains no credential: grep for the values of
      `NMEM_API_KEY` / `OPENCODE_API_KEY` finds nothing in the generated patch.
- [ ] A second `just dsh` changes nothing (idempotent seeds; plugin install is a
      no-op).
- [ ] With the desktop app running, the step warns and writes nothing.
- [ ] On a Linux host the packages step and the env-link both skip, and no
      dangling `~/.local/bin/dsh` is left behind.
- [ ] `just check` passes, including the new `only` validation for env links and
      the DSH data file.

## Rollout

1. Add the data file and `scripts/dsh.py` with `--plan` / `--print-patch` /
   apply; no wiring yet.
2. Add the cask entry and the `.local/bin/dsh` env link with the `only` gate;
   extend `check.py`.
3. Add `run_onchange_after_28-dsh.sh.tmpl` and the `just dsh` recipe.
4. Document in README (`DSH on macOS`, Layers and ownership, guardrails) and
   record ADR-0014; append the refinement note to ADR-0011's update log.
5. Rehearse on a scratch `DSH_HOME`, then on the reference host.

**Rollback:** delete the wrapper and the two inventory/link entries; `~/.dsh`
keeps whatever the last run generated, which the app composes harmlessly. No
runtime state is moved.

## Decision log (2026-10-26)

All of the above is the owner's decision, verified against the installed app's
bundle sources, the formulae.brew.sh API and scratch-`DSH_HOME` experiments on
2026-10-26. The load-bearing calls:

1. **Cask, not a pinned feed ZIP** — official and self-updating; the feed ZIP
   stays documented as the fallback for a stale or blocked Homebrew.
2. **Link the bundle CLI rather than the app's own command manager** — no admin,
   and `~/.local/bin` is the repo's own directory.
3. **Script generation for the two app-never-written files, not chezmoi** — the
   only way to keep secrets out of the repo while composing `!!js` values, and
   `check.py` can assert the property.
4. **Seeds are add-only / create-once; the app's files are never rewritten** —
   the same seed contract ADR-0012 uses for `~/.pi`, applied to the two files
   `dsh plugin` reads.
5. **Capability only** — the four preference rows stay app-owned; a broken
   onboarding or theme is not something a dotfiles repo should own.
6. **The step lives in the apply path**, with `just dsh` for a by-hand re-run;
   only the secrets are manual.

This RFC is **Resolved**; the outcome is [ADR-0014](../plans/adr-0014-dsh-practice-restore-2026-10-26.md).
