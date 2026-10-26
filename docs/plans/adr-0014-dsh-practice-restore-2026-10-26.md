# ADR-0014: DeepSeek Harness is restored from the repo as a cask, a bundle link and one generated home patch

| Field | Value |
| --- | --- |
| Status | accepted |
| Date | 2026-10-26 |
| Supersedes | — (refines ADR-0011's 2026-10-23 "DSH needs no projection" note; see its update log) |
| Keeps | ADR-0013 (layout and ownership rule), ADR-0010 (plan and clearance), ADR-0011 + ADR-0012 (agent toolchain — DSH stays outside the manifest) |

## Context

RFC-0008 records the gap. DSH is the owner's primary harness, but it is the one
agent with no restore path: the app is installed by hand, signed in by hand and
configured through its Settings UI, so the plugin set, the model/provider/
web-search capability and the nowledge-mem MCP server exist only on the live
machine. README's "*DSH reads the shared roots, so it needs no projection*" is
true for ADR-0011's manifest plane and silent about the harness's own state.

Three measured facts decide the mechanism (reference host, 2026-10-26).

**The app owns every profile file.** `$DSH_HOME` (default `~/.dsh`) holds a
directory per profile. `profiles/<name>/cordis.yml` is regenerated on every boot;
`profiles/<name>/cordis.patch.yml` is written by the Settings UI and dshmarket;
`profiles/<name>/package.json` and `pnpm-workspace.yaml` are the plugin manager's.
This is the same exclusion ADR-0013 draws for runtime-writable agent config: none
of it may be a chezmoi source entry. Exactly one composition point has no writer:
`$DSH_HOME/cordis.patch.yml`, the machine-wide **home patch**. In the bundled
boot code (`app.asar/dsh/node_modules/@deepseek-ai/dsh-app-boot/lib/index.js`,
`readProfilePatches`) the patch order is bundle layers → the profile patch →
the home patch → CLI overlays, so the home patch is composed after every
profile's own patch and applies to every profile.

**The home patch can carry environment references.** The patch dialect supports
`!!js` expressions, and `loadLayeredEnv` applies `$DSH_HOME/.env` only where the
inherited process environment leaves a name unset. A secret can therefore enter
the composed tree without being written into the generated patch — and an
exported variable still wins over the file, so a shell environment keeps
precedence.

**The CLI is inside the bundle, and the cask is the only sensible install
channel.** `Contents/Resources/runtime/cli/bin/dsh` is a POSIX-sh launcher that
resolves the bundle and execs Electron as Node against
`app.asar/dsh/node_modules/@deepseek-ai/dsh-desktop-host/lib/cli.js`; the cask
has no CLI artifact and the app's own "Manage dsh command" writes
`/usr/local/bin` (admin). The cask is `homebrew/cask`, `auto_updates=true`, arm64,
macOS ≥ 13, and its `zap` list trashes `~/.dsh`.

Two operational constraints are part of the context: the repo is stdlib-only and
has no YAML parser, so it cannot merge an app-owned YAML file; and the desktop
app probes
`~/Library/Application Support/@deepseek-ai/dsh-desktop/SingletonLock`, while the
plugin manager's `profiles/desktop/package.json.lock` is not held by a running
app, so that lock does not make concurrent writes safe.

## Decision

> In the context of a macOS workstation whose primary agent harness is installed,
> signed in and configured by hand, so that its working capability otherwise
> exists on exactly one machine,
> facing an app that owns every profile file, a repo that may not own runtime
> agent config, and no YAML parser to merge with,
> we decided for **the official Homebrew cask, a `~/.local/bin/dsh` link into the
> app bundle, and one script-generated machine-wide home patch plus a 0600
> `.env`, driven by a reviewed `home/.chezmoidata/dsh.toml` inventory**,
> and against a chezmoi source entry under `~/.dsh`, against seeding the
> app-owned profile patch, and against adding DSH to the ADR-0011 agent
> manifest,
> to achieve a fresh machine that comes up with the same DSH capability from the
> repo plus machine-local secrets,
> accepting a home patch that is machine-wide (so `web` and `tui` profiles get it
> too), a restored surface deliberately narrower than the owner's preferences,
> and a restore that can lag a major app self-update until the step is re-run.

### Ownership — one writer per file

| Path | Writer | The repo's part |
| --- | --- | --- |
| `$DSH_HOME/cordis.patch.yml` | `scripts/dsh.py` (the app never writes it) | generated whole, from `dsh.toml` |
| `$DSH_HOME/.env` (0600) | `scripts/dsh.py` | generated from declared secret names; values come from the process environment |
| `profiles/desktop/package.json` | `dsh plugin` / pnpm, seeded by `dsh.py` | **add-only** seed: declared plugins, pinned versions, ordered bundle list |
| `profiles/desktop/pnpm-workspace.yaml` | pnpm, seeded by `dsh.py` | seed only when the file is missing (`allowBuilds`, `minimumReleaseAgeExclude`) |
| `profiles/*/cordis.yml`, `profiles/*/cordis.patch.yml` | the app | never touched |
| `profiles/*/node_modules/`, `.dsh-market/` | pnpm / the app | never touched (caches) |
| `.credentials.yaml`, `sessions/`, `storages/`, `cache/` | the app | never touched, never persisted |

The seed contract is ADR-0012's, one layer out: values are written only where the
file does not already carry them, so a running app's own writes survive. The
two generated files are whole-file replacements precisely because nothing else
writes them.

### What is restored — capability, not preference

| Restored | Why it is capability |
| --- | --- |
| 13 plugin bundles, ordered, six of them pinned to exact versions | without the order and the versions the desktop profile is a different product |
| pnpm `allowBuilds` + `minimumReleaseAgeExclude` | the native pieces (`node-pty`, `koffi`, …) do not build without them |
| Default model (provider, model, reasoning effort) | it is what every new session starts from |
| `opencode` provider with `apiKeyEnv: OPENCODE_API_KEY` | the provider does not exist until it is declared |
| Subagent model allowlist | a capability the owner relies on, seven models |
| Web search / fetch providers | without them the harness has no web access |
| nowledge-mem MCP server | the shared knowledge graph is the memory plane |

**Not restored, deliberately:** the config rows for `ui-chat`, `ui-settings`,
`ui-settings-account` and `better-sidebar`. These are app-owned preferences and
onboarding; their bundles still load with app defaults, and the Settings UI keeps
authority over them. The `~/.agents` instruction and skills roots are not in
scope at all — ADR-0011 already single-sources them and DSH reads them directly.

### Install channels

**App — one cask entry.** `home/.chezmoidata/packages.toml:120-136` adds
`deepseek-harness` with `cask = true`, `only = "darwin"` and
`probe_darwin = ["/Applications/DeepSeek Harness.app"]` (probe the bundle, not
`bin`: the CLI is a symlink *into* it). `scripts/packages.py:86-87` already
routes `cask = true` to `brew install --cask`, so no new machinery. A GUI `.app`
has no mise backend, and the scripts' own download path stays for tools, not for
signed desktop bundles.

Rejected: any mise backend (none exists for a `.app`); the app's own command
manager as the CLI channel (writes `/usr/local/bin`, needs admin); pinning the
nightly feed ZIP (the feed publishes `nightly-mac.yml` and a sha512'd ZIP, but it
is not official packaging — kept as the documented fallback for a stale or
blocked Homebrew).

**CLI — one env link with an OS gate.** `home/.chezmoidata/envlinks.toml:222-227`
links `.local/bin/dsh` to the bundle launcher. Because that target only exists on
macOS, this change adds a generic `only = "darwin" | "linux"` gate to the
inventory (documented at `envlinks.toml:16-17`) for both entries and plain links,
using the same OS family ids as `packages.toml`: `env_links.py:52` computes the
family, `env_links.py:112-120` skips a non-matching link before placing it, and
`check.py:62-82` rejects any other value. A headless Linux host therefore never
gets a link that could only dangle — the same class of check `packages.toml`'s
`only` already had.

### The inventory and the generator

`home/.chezmoidata/dsh.toml` is the single reviewed description: the desktop
profile's `bundles` order and `plugins` map (exact versions), the pnpm workspace
settings, the patch rows (`[[dsh.patch]]`), the token-gated MCP server
(`[[dsh.mcp]]`) and the secret **names**. `scripts/dsh.py` reads it with
`tomllib` and has three modes: `--plan` (what would change), `--print-patch`
(render the home patch to stdout) and the default apply.

The apply is deliberately small and ordered:

1. Refuse to write while the app runs — probe the desktop singleton lock,
   warn, exit 0. The plugin manager's own lock is not held by the app, so this
   probe is the only safe guard.
2. Render `$DSH_HOME/cordis.patch.yml` from the inventory. A secret is a `!!js`
   expression — **one single-quoted scalar** reading the variable from
   `process.env`, e.g. `!!js '"Bearer " + process.env.NMEM_API_KEY'` — so no
   secret value is ever written into the patch or the repo. The quoting is not
   style: the unquoted form is a YAML syntax error (`bad indentation of a
   mapping entry`), which is why the generator emits the scalar form.
3. Write `$DSH_HOME/.env` (0600) with `NAME=value` for each declared secret that
   is present in the process environment. This exists because a GUI-launched app
   does not necessarily inherit a login shell's exports, while `loadLayeredEnv`
   always reads this file.
4. Seed `profiles/desktop/package.json` add-only and
   `pnpm-workspace.yaml` only when missing — this is what makes a first
   bootstrap possible, because `dsh plugin` cannot initialize a profile that does
   not exist, but accepts a pre-seeded manifest.
5. Run the app's own `dsh plugin --profile desktop install` — the projection
   goes through the app's CLI, never through the repo writing `node_modules`.
   Measured: ~25 s unattended on the reference host.

The home patch's MCP row is a root `insert:` list entry, not a bare id row: a
bare row naming a new id is warned and skipped by the loader, which is why an
insert is the only way a server joins the composed tree. The new row targets
`@deepseek-ai/dsh-mcp-client` with `serverName: nowledge_mem`, streamable HTTP,
the owner's header set, and its bearer supplied by the env reference.

### Why DSH stays outside the ADR-0011 manifest

ADR-0011's 2026-10-23 entry records the reasoning and it survives this change:
DSH reads `~/.agents` directly, so it has no instruction projection to declare;
an `all` default selection in `--agents` would try to install a macOS `.app` on
Linux CI; and its MCP surface here is one machine-level server, not the shared
`MCP_SERVERS` projection. This ADR adds a *third*, repo-owned path next to the
manifest — a restoration step for the harness's own configuration — and does not
turn DSH into an `Agent` subclass. README's "needs no projection" line becomes
"needs no entry in that manifest", which is what it always meant.

### Wiring and order

`home/.chezmoiscripts/run_onchange_after_28-dsh.sh.tmpl` is a one-liner wrapper
per the `.chezmoiscripts/` convention (README — Conventions), hash-keyed on
`dsh.toml` and `dsh.py` and darwin-gated. It runs after
`run_onchange_after_20-packages` because it needs the cask's `dsh` CLI to exist;
`just dsh` re-runs it by hand. Nothing goes to the deferred post-login script:
the step itself is unattended, and the only thing that needs a human is adding
secrets (next section).

### Secrets and login stay manual

`NMEM_API_KEY` (the MCP bearer) and `OPENCODE_API_KEY` (the provider) live in the
machine-local `~/.exports.local`; the step mirrors them into `$DSH_HOME/.env`.
Nothing else is manual: the account sign-in, the OAuth device flow and
`~/.dsh/.credentials.yaml` are never provisioned, because they are credentials a
repo must not carry. A missing secret is a warning plus `just dsh` after adding
it, not a failed apply — the generated patch composes either way.

### Verification

- `just check` — data validation (including `dsh.toml` and the new `only`
  values), script compile/`--help`, and a full chezmoi render per environment.
- `./bootstrap.sh --dry-run --verbose` — the plan carries the packages and
  env-link rows when the cask or the CLI link is missing, and renders the
  `run_onchange_after_28-dsh` step; the step itself runs inside `chezmoi apply`,
  not in the bootstrap plan, exactly like the rime and setup steps.
- A scratch-`DSH_HOME` rehearsal: `DSH_HOME=$(mktemp -d) just dsh` materializes
  the bundles, then `DSH_HOME=<that dir> dsh --profile web --dump-config` must
  exit 0 and name the generated home patch as the last layer; the desktop
  profile's own load is confirmed by the app's first launch.
- `just dsh --print-patch` and grep for the secret values: the generated patch
  must contain none (the no-token assertion).

## Alternatives Considered

| Alternative | Why rejected |
| --- | --- |
| chezmoi source entry for `$DSH_HOME/cordis.patch.yml` | Needs chezmoi-rendered secrets (or a token-less MCP row YAML cannot conditionally omit), and violates the "a file a tool rewrites is never a source entry" rule for the one file this change exists to generate. Script generation keeps it secret-free and lets `check.py` assert that. |
| Textually seeding the app-owned `profiles/desktop/cordis.patch.yml` | Stdlib-only repo has no YAML parser; the app rewrites/renames the file; Settings saves would fight the seed. |
| A `DshAgent` subclass in `scripts/agents.py` | ADR-0011's 2026-10-23 entry: DSH reads `~/.agents` directly, an `all` selection would install a macOS `.app` on Linux CI, and its MCP surface is one machine-level server. |
| Pinned feed-ZIP download instead of the cask | The feed exists (`nightly-mac.yml` + sha512'd ZIP) and is the right fallback for a blocked brew, but it is not official packaging and adds update machinery the cask already has. |
| Env-linking `~/.dsh` onto the state root | Non-goal for v1: it would move a live `~/.dsh` out from under a running app, and most of `~/.dsh` is runtime state rather than repo config. Follow-up, with a `preserve_dir`-style migration. |
| Make the home patch profile-scoped | The app does not write a third patch layer, and a per-profile file would have to be generated for profiles that do not exist yet. The machine-wide composition point is the feature. |

## Consequences

- **Fresh-machine order is fixed:** cask (packages step) → seed + generate +
  plugin install (DSH step) → first app launch, which finds the bundles already
  materialized. If the app launches first, it creates the profile from the web
  template and the add-only seed lands on top; both orders work.
- **Two secrets are the only manual part**, and the remedy is `just dsh` after
  adding them. Nothing in the apply path prompts.
- **Pinned rows become repo-owned.** Settings shows "overridden by a home patch"
  for those entries and saving a new default there no-ops; the in-chat model
  picker still works per session.
- **The home patch is machine-wide.** `web` and `tui` profiles receive the
  providers, the MCP server and the default model. Intended — one place to pin
  capability — but it is new behaviour for profiles that used to be isolated.
- **`~/.dsh` is still ephemeral on container recreation.** Only the two generated
  files and the profile manifest are restored; sessions and history are not.
  `envlinks.toml` for `~/.dsh` is the recorded follow-up.
- **A major app self-update can outrun the pins.** Re-running the step (or
  `dsh plugin allow-version` for a moved peer range) is the repair; the failure
  is a compatibility warning at boot, not silent.
- **Homebrew's local index can be stale.** The reference host's index answers
  `No Cask with this name exists` while the app is installed; formulae.brew.sh
  is authoritative, so that message means "update the index", not "the cask is
  gone".
- **`brew uninstall --zap deepseek-harness` is forbidden.** The cask's zap list
  trashes `~/.dsh` — credentials, sessions and the generated config with it.
- **The cask is arm64 and macOS ≥ 13 only.** Linux hosts are headless: the
  package entry and the env link both skip, and the plan records the skip.
- **DSH remains outside the agent manifest**, so a future agent joining by the
  ADR-0011 recipe still needs this ADR's separate restore path if it is a
  desktop app rather than a CLI.
