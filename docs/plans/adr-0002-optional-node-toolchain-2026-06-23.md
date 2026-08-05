# ADR-0002: Optional Node Toolchain (nvm + Node LTS + pnpm)

| Field | Value |
|---|---|
| Status | accepted |
| Date | 2026-06-23 |

## Context

`npx` was not available on bootstrapped machines because no Node runtime was
installed. `npx` ships with `npm`, which ships with `node` — so providing a
Node install satisfies the `npx` requirement. pnpm was requested as an
additional package manager.

The repo already has an established extension point: self-registering
`OptionalComponent` subclasses in `installers/components.py`, each exposed as a
`--optional-components` token (and via `DOTFILE_BOOTSTRAP_OPTIONAL_COMPONENTS`).
Siblings like `claude`, `btm`, and `fdfind` are cross-platform components that
either branch on OS or curl an upstream install script directly. This new
capability fits that pattern rather than touching the core bootstrap flow.

## Decision

Add a single optional component `node` that installs the whole toolchain as one
unit: **nvm → Node LTS → pnpm**.

### 1. Granularity: one component, not two

A single `node` component installs nvm, the LTS Node, and pnpm together — rather
than separate `nvm` and `pnpm` tokens. The three form one toolchain serving one
goal, and a split would introduce an install-ordering dependency (pnpm needs
Node present first) for no real flexibility gain.

### 2. nvm: pinned install script, driven within bootstrap

- Fetch nvm's official `install.sh` pinned to a specific tag (currently
  `v0.40.5`, which carries the CVE-2026-10796 fix). The pin is bumped
  deliberately, never floated to a moving branch.
- Download then execute in two steps (curl to a temp file, then `bash` it) —
  matching the `claude` component's rationale that a piped `curl | bash` masks
  an upstream curl failure behind the pipeline's exit code.
- Curl upstream directly with **no gitee/mirror fallback**, matching the
  `claude` and `starship` components.
- Because nvm is a shell *function* (not a binary on `PATH`), running it in a
  fresh subprocess fails. So after installing, source `$NVM_DIR/nvm.sh` and run
  `nvm install --lts` + pnpm enablement inside a **single `bash -c`** that has
  the freshly-installed nvm loaded. This drives the install to completion so
  `node`/`npm`/`npx`/`pnpm` work immediately after bootstrap, not only after the
  user opens a new shell.

### 3. Node version: LTS

`nvm install --lts`. nvm alone installs no Node and therefore no `npx`; LTS is
the conventional, stable default.

### 4. pnpm: Corepack

`corepack enable pnpm`, using the Corepack shim bundled with Node — one command,
no extra network fetch, version pinnable per-project via the `packageManager`
field. Rejected alternatives: `npm install -g pnpm` (global pins to one nvm Node
version and won't follow `nvm use`); the standalone pnpm install script
(redundant network fetch when Node is already present).

### 5. OS support and grouping

`supported_os = None` and `groups = frozenset({"all"})` — nvm's install script
covers macOS, Linux, and WSL, so the component is cross-platform and joins the
`all` alias group like its siblings.

## Consequences

- `--optional-components node` (or any group containing it, e.g. `all`) installs
  nvm, Node LTS, and pnpm; `npx` and `pnpm` are usable right after bootstrap.
- nvm is the only thing that touches the user's shell rc — the install script
  appends its sourcing lines as usual; interactive shells pick up `nvm`/`node`
  on next launch.
- The nvm version is a maintained pin: security and feature updates require a
  conscious bump of `Node.NVM_VERSION`.
- There is no way to get nvm without also getting pnpm; if that need arises, the
  component can later be split (see rejected granularity option).
- No gitee mirror fallback: on networks where `raw.githubusercontent.com` is
  unreachable, this component will fail — consistent with `claude`/`starship`.
