# RFC-0001: Migrate dotfiles from Python bootstrap to Nix flake + standalone Home Manager

- Status: Draft
- Date: 2026-07-09
- Owners: HernandoR (with Claude)

## Summary

Replace the Python-driven bootstrap (`bootstrap.sh` → `uv` → `main.py` +
`installers/`) and its rsync-stage-symlink dotfiles pipeline (ADR-0001) with a
**Nix flake + standalone Home Manager** configuration that manages user-level
tooling and dotfiles declaratively and reproducibly. Home Manager runs
*standalone* (not NixOS, not nix-darwin) and symmetrically on both macOS and
Debian/Ubuntu. System-level provisioning that Home Manager cannot own on a
non-NixOS host (docker daemon, CUDA, NVIDIA drivers, LLVM, GUI apps, SSH-key
deployment, Claude OAuth post-setup) stays in a slimmed imperative layer.

## Motivation

The current bootstrap works but is imperative and non-reproducible in ways that
bite across machines:

- **No lockfile / version drift.** Tool versions are a mix of pinned tags
  scattered through `installers/components.py` (nvm `v0.40.5`, jj `v0.43.0`,
  mergiraf `v0.17.0`, CUDA `12.6`, LLVM `18`) and *unpinned* upstreams (brew
  formulae, `apt install`, `starship.rs/install.sh`, `claude.ai/install.sh`).
  Two machines bootstrapped a month apart do not converge.
- **Runtime plugin fetches.** zsh plugins are pulled by **antigen at shell
  startup** and oh-my-zsh is cloned at install time — the shell environment is
  assembled imperatively at runtime, not described anywhere as data.
- **Bespoke linking machinery.** ADR-0001's `source → stage → symlink` pipeline
  (rsync `sources/root` → `~/dotfiles` → symlink `$HOME`), the
  backup-on-collision logic, and `_staging_has_unlinked_items` re-implement what
  Home Manager does natively (generation-based symlinking with automatic
  backups).
- **Whole-machine state is not legible.** Answering "what is installed and
  configured on this box, and can I reproduce it?" requires reading imperative
  Python. A flake + `flake.lock` answers it declaratively.

The pieces the current design got *right* (rc-file ownership per ADR-0004,
Claude post-setup per ADR-0005, SSH-key-by-copy per ADR-0006) are preserved as
constraints on the new design, not thrown away.

## Goals

- User-level tooling and dotfiles are **declarative and reproducible** via a
  Nix flake pinned by `flake.lock`.
- The **starship prompt survives with its theme intact** (the stated hard
  constraint).
- Preserve the working zsh UX — in particular the **fzf-tab** completion
  experience — plus git (with the mergiraf merge driver), tmux, fzf, and the
  curated CLI toolset.
- **Cross-platform and symmetric**: the same flake serves macOS and
  Debian/Ubuntu, with **no OS reinstall** required.
- **Works on CN networks** via a binary-cache mirror (USTC/TUNA), matching the
  repo's existing mirror-first posture.
- **Project shell scripts keep working** from the login shell (no Nix purity
  breakage for `#!/bin/bash` / `#!/usr/bin/env bash`).
- The migration is **verifiable in a throwaway OrbStack container** before it
  touches a real home directory.

## Non-Goals

- **No nix-darwin and no NixOS.** Explicitly declined (2026-07-09 grilling).
- **No declarative GUI casks or macOS system defaults.** The `init/` plists
  (`.terminal`, `.itermcolors`, spectacle, Sublime prefs) are dropped from
  scope; GUI apps are installed imperatively via brew or by hand.
- **No secrets in Nix.** SSH private keys never enter the world-readable Nix
  store; the copy-based deployment (ADR-0006) is retained.
- **No system daemons/drivers via Nix** on non-NixOS hosts: docker, CUDA,
  NVIDIA, LLVM `update-alternatives` remain imperative and Linux-scoped.
- Not a rewrite of the Claude Code post-setup logic (ADR-0005) — it is ported,
  not redesigned.

## Proposal

### Settled decisions (2026-07-09 decision-grilling)

1. **Standalone Home Manager (user-level)**, with a thin imperative layer for
   system-level concerns. Top-level flake outputs are `homeConfigurations`.
2. **Full native rewrite, "the Nix way."** Drop oh-my-zsh, antigen, and
   powerlevel10k (`.p10k.zsh`). Rebuild shell/git/prompt/tmux with Home Manager
   modules; keep the curated CLI tools and a cleaned-up path/exports.
3. **Symmetric on both platforms, no nix-darwin.** GUI casks are not forced;
   macOS system-defaults plists are dropped.
4. **Runtimes: `mise` (node, rust) + `uv` (python).** Matches the referenced
   `bgub/nix-macos-starter`; keeps the uv workflow the repo already uses.

### Proposed repository structure

```
flake.nix              # inputs: nixpkgs + home-manager; outputs: homeConfigurations.{<mac>,<linux>}
flake.lock
home/
  default.nix          # imports + username/homeDirectory/stateVersion (per-platform via specialArgs)
  packages.nix         # home.packages: fd bottom gh jujutsu mergiraf ripgrep tree tmux vim wget rsync coreutils git-lfs nerd-fonts…
  shell.nix            # programs.zsh (autosuggestion/syntaxHighlighting/completion + fzf-tab + zsh-completions), programs.fzf, sessionVariables/sessionPath, initContent
  starship.nix         # programs.starship.settings (ported from .config/starship.toml)
  git.nix              # programs.git (mergiraf merge-driver + aliases, ported from .gitconfig)
  tmux.nix             # programs.tmux (ported from .tmux.conf)
  mise.nix             # programs.mise + activation (node LTS + rust stable)
  misc.nix             # xdg.configFile.source: helix/lvim/zellij/alacritty/condarc/ruff verbatim
hosts/
  <mac-host>/home.nix  # per-machine overrides (username, extra pkgs)
  <linux-host>/home.nix
platform/              # thin imperative layer (slimmed reuse of today's main.py/installers)
  bootstrap.sh         # install Nix (Determinate) + configure CN mirror → home-manager switch --flake .#<host>
  system.py            # docker / cuda / nvidia / llvm / apt·brew system packages (Linux/mac system-level)
  claude.py            # Claude Code deferred OAuth post-setup (ADR-0005)
  ssh.py               # SSH-key copy (secrets, out of Nix — ADR-0006)
```

### Disposition of current assets

**Into the Nix flake (Home Manager native):**

| Today | Home Manager |
|---|---|
| `.zshrc` / oh-my-zsh / antigen | `programs.zsh` (rebuilt, no omz/antigen) + `zsh-fzf-tab` / `zsh-completions` plugins |
| fzf (necessary component) | `programs.fzf` |
| starship + `.config/starship.toml` | `programs.starship.settings` |
| `.gitconfig` / `.gitattributes` / mergiraf | `programs.git` (`extraConfig` registers the mergiraf merge driver) |
| `.tmux.conf` | `programs.tmux` |
| node (nvm) / rust (rustup) | `programs.mise` |
| fdfind / btm / gh / jj / mergiraf / brew formulae | `home.packages` (nixpkgs) |
| `.aliases` / `.exports` / `.path` / `.functions` | `shellAliases` / `sessionVariables` / `sessionPath` / `initContent` |
| `.inputrc` `.curlrc` `.wgetrc` `.condarc` `.lscolors` `ruff.toml` helix/lvim/zellij/alacritty | `home.file.source` / `xdg.configFile.source` (verbatim; not worth nixifying) |

**Kept in the thin imperative layer** (Home Manager cannot own these on a
non-NixOS host): docker / docker-rootless, CUDA, NVIDIA drivers, LLVM +
`update-alternatives`, apt/brew **system** packages and GUI casks, Claude
deferred OAuth, SSH-key copy, codegraph (not in nixpkgs), `chsh` to zsh.

**Dropped:** oh-my-zsh / antigen / `antigen.zsh`, `.p10k.zsh` (starship is the
kept prompt), the rsync→stage→symlink pipeline (ADR-0001, superseded by Home
Manager's own linking), the `init/` plists and terminal themes.

### Provisional defaults (proposed; open for challenge)

- **Nix installer:** Determinate installer (flakes on by default, clean
  uninstall, survives macOS SIP).
- **CN binary cache:** USTC `https://mirrors.ustc.edu.cn/nix-channels/store`
  primary + official `cache.nixos.org` fallback, written to
  `~/.config/nix/nix.conf`. Both proxy the official cache and share the same
  signing key, so no extra `trusted-public-keys` entry is needed.
- **Secrets:** SSH private keys stay out of the Nix store; copy-based
  deployment (ADR-0006) is retained in the imperative layer.

## Alternatives Considered

| Alternative | Why Not |
|---|---|
| **nix-darwin + nix-homebrew (macOS)** | Would make casks and macOS defaults declarative and matches the reference starter, but the owner explicitly wants symmetric standalone HM without touching the system layer / `sudo darwin-rebuild`. Casks are "not forced"; plists are dropped. |
| **Full NixOS (Linux) + nix-darwin (mac)** | Most declarative, but Linux boxes (existing Debian/Ubuntu/WSL/servers) would need reinstalling as NixOS — not viable. |
| **`nix-shell` / `nix develop` only** | Ephemeral dev environments; do **not** persist the prompt/dotfiles into the login shell, so they cannot meet the "starship theme works in my shell" goal. |
| **Verbatim `home.file.source` for all configs** (fastest parity) | Rejected in favor of a native rewrite: the owner wants the Nix-native form and to drop omz/antigen/p10k rather than carry them forward. (Verbatim sourcing is still used for low-value leaf rc files.) |
| **Pure-nixpkgs runtimes** (node/rust pinned by `flake.lock`) | Most reproducible, but per-project version switching is clumsier than mise; owner chose mise for parity with the starter and existing uv workflow. |
| **Keep runtimes fully imperative** (nvm/rustup/uv unchanged) | Smallest change but least "Nix way"; only uv is retained. |

## Risks

- **CN first-install latency.** Installing Nix and warming the store over CN
  links is slow even with a mirror. *Mitigation:* configure the USTC/TUNA
  substituter before the first `home-manager switch`; the `platform/bootstrap.sh`
  step writes `nix.conf` first.
- **fzf-tab load order in the native zsh module.** The current setup depends on
  fzf-tab loading *after* `zsh-completions` and *before*
  autosuggestions/syntax-highlighting (see `context.md`). *Mitigation:* control
  ordering via the `programs.zsh.plugins` list order and `initContent` +
  `lib.mkOrder`; verify the completion menu is fzf-driven in the container test.
- **nixpkgs packaging gaps.** mergiraf may or may not be in nixpkgs on the
  pinned channel; codegraph is not. *Mitigation:* mergiraf → nixpkgs if present,
  else keep the musl-binary install in the imperative layer; codegraph stays
  imperative regardless. (Open question below.)
- **Login-shell change.** zsh now comes from the Nix profile, not the system
  path; `chsh` must point at the right binary and `/etc/shells` may need it.
  *Mitigation:* handled in the imperative layer, idempotently (as today).
- **mise reproducibility gap.** mise downloads runtimes imperatively, so that
  slice is not `flake.lock`-reproducible. *Accepted* trade-off per decision 4.
- **Transition breakage on the real home.** A first switch backs up/overwrites
  live dotfiles. *Mitigation:* the OrbStack container test and `-b backup`
  gate any switch on a real machine.

## Open Questions

1. **`.bash_prompt` / bash framework** — drop entirely (zsh-only), or keep a
   minimal `programs.bash` for non-interactive/login-shell fallbacks?
2. **`.screenrc`** — still used, or drop? (`.tmux.conf` is the kept multiplexer.)
3. **1Password** — casks are not forced, but do we want the **1Password CLI**
   (`_1password` / `op`) via `home.packages`, or nothing?
4. **mergiraf packaging** — is it in nixpkgs on the target channel? If not,
   keep the musl-binary install imperative.
5. **CN mirror choice** — USTC vs TUNA vs SJTU as primary; confirm the
   provisional USTC default.
6. **Host set** — how many machines / hostnames, and their platforms
   (Apple Silicon vs x86 mac; Debian vs Ubuntu; WSL?) — needed to name the
   `hosts/<host>` entries and pick `system` strings.
7. **Fate of `main.py` / `installers/`** — slim in place, or carve the retained
   imperative bits into a new `platform/` tree and retire the rest?
8. **Transition strategy** — big-bang cutover vs. run the flake alongside the
   existing pipeline for a period.
9. **`home.stateVersion`** — pin to the first-install release (e.g. `25.05`).
10. **Lix vs CppNix** — the branch is `feat/lix-based`; do we standardize on
    Lix (drop-in for flakes/HM) or plain Nix via the Determinate installer?

## Acceptance Criteria

- [ ] `nix flake check` passes on the flake.
- [ ] In a throwaway **OrbStack Debian container**: install Nix → configure the
      CN substituter → `home-manager switch --flake .#<linux-host>` succeeds
      from a clean home.
- [ ] In that container, a fresh `zsh` login shows the **starship prompt with
      the ported theme**, `fzf-tab` drives tab completion, autosuggestions and
      syntax-highlighting load in the correct order.
- [ ] `git` uses the configured identity and the **mergiraf merge driver** is
      registered (`git config --get merge.mergiraf.driver`).
- [ ] `tmux`, `fzf`, and the CLI toolset (`fd`, `gh`, `jj`, `rg`, `btm`, …) are
      on `PATH` and runnable.
- [ ] `mise` provides node LTS and rust stable; `uv` still runs.
- [ ] A sample project script with `#!/usr/bin/env bash` runs unchanged from the
      HM-configured login shell.
- [ ] macOS: the same flake builds and switches on the owner's machine (guarded
      by `-b backup`), with starship/zsh/git/tmux verified.

## Rollout

1. Scaffold `flake.nix` + `home/` and get `nix flake check` green.
2. **Verify Linux path first in OrbStack** (Debian container) end-to-end against
   the acceptance criteria — this is the safe, destructive-op sandbox.
3. Add `hosts/<mac-host>` and switch on the real macOS machine with `-b backup`;
   verify starship theme + zsh UX are intact.
4. Port the retained imperative bits into `platform/` (docker/cuda/nvidia/llvm,
   Claude post-setup, SSH-key copy, `chsh`); retire the rsync→stage→symlink
   pipeline and the dropped assets.
5. Update `README.md` / `context.md`; supersede ADR-0001 (linking) and revisit
   ADR-0002/0004 (Node necessary component, phase separation) in the new ADR.

**Rollback:** the pre-switch dotfiles are preserved by Home Manager's backups
(`-b backup`); reverting is `home-manager generations` + `home-manager switch
--rollback`, or restoring the backups and removing the Nix profile. The old
Python pipeline remains on `main` until the new path is verified on real
hardware.

## Discussion Log

### 2026-07-09 — Initial draft (decision-grilling session, HernandoR + Claude)

Four structural decisions were resolved by grilling (recorded in Proposal
§"Settled decisions"):

1. Scope → standalone Home Manager (user-level) + thin imperative layer.
2. Config strategy → full native rewrite; drop omz/antigen/p10k.
3. macOS approach → symmetric standalone HM, no nix-darwin; casks not forced;
   plists dropped. (This revised the earlier lean toward nix-darwin after
   noting the owner's preference against touching the system layer.)
4. Runtimes → mise (node/rust) + uv (python).

Grounding facts were gathered from Context7 (`/nix-community/home-manager`,
`/websites/nix-darwin_github_io_nix-darwin_manual`, `/zhaofengli/nix-homebrew`,
`/nixos/nix`, `/lix-project/lix`) and by reading `bgub/nix-macos-starter`.

New constraint added mid-session: **OrbStack is available**, so the Linux path
can be verified in a Debian container before touching any real home — folded
into Acceptance Criteria and Rollout.

Open Questions 1–10 remain for the next discussion round (step 2).

<!-- Append future discussion below this line; do not rewrite entries above. -->

### 2026-07-09 — Discussion round 2 (Open Questions resolved)

The Open Questions from the initial draft were worked through. Resolutions
(the ADR will carry these as clean, settled intent):

- **Q1 — bash framework → DROP.** Go fully zsh-only. `.bashrc`,
  `.bash_prompt`, `.bash_profile`, `.bash_logout` are dropped; no
  `programs.bash` fallback.
- **Q2 — `.screenrc` → DROP.** tmux is the kept multiplexer; GNU screen is not
  used.
- **Q3 — 1Password → ADD the CLI only.** `_1password-cli` (`op`) goes into
  `home.packages`. The GUI app stays imperative (brew / by hand); no cask
  management.
- **Q4 — mergiraf packaging → DEFERRED to implementation.** Verify presence in
  nixpkgs on the pinned channel inside the OrbStack container; if absent, keep
  the musl-binary install in the imperative layer. codegraph stays imperative
  regardless.
- **Q5 — CN mirror → USTC primary + official fallback** (provisional default
  accepted), written to `~/.config/nix/nix.conf` by `platform/bootstrap.sh`.
- **Q6 — Host set → Mac + multiple Linux/servers.** This machine is
  **aarch64-darwin (Apple M3 Max)**. The fleet may include x86_64-linux,
  aarch64-linux, and WSL. Structural implication: the flake needs a **generic
  multi-host / multi-system helper** (e.g. a `mkHome`
  function, or flake-utils / flake-parts) to enumerate `homeConfigurations`
  per host across several `system` strings — not the single hard-coded output
  of the reference starter. `hosts/<host>/home.nix` per machine.
- **Q7 — `main.py` fate → carve retained bits into `platform/`,** retire the
  rest (rsync/stage/symlink pipeline and the dropped installers).
- **Q8 — Transition → parallel until verified.** Keep the old Python path on
  `main`; develop and verify the flake on `feat/lix-based` (container + real
  machine with `-b backup`) before cutover and retirement.
- **Q9 — `home.stateVersion` → pin at scaffold time** to the then-current
  stable release; do not bump casually afterward.
- **Q10 — Nix implementation → Lix.** Matches the `feat/lix-based` branch. Lix
  is a drop-in for the flakes/Home-Manager workflow; only its internal C++ API
  intentionally diverges from CppNix, which does not affect this user-level
  usage.

Only Q4 remains truly open (a packaging fact to confirm during implementation);
everything else is settled and ready to summarize into an ADR.

### 2026-07-09 — Discussion round 3 (implementation findings)

Scaffolding and building the flake on the real machine surfaced facts that
refined the design; the ADR reflects the settled form.

- **Nix is already Lix 2.95.2 on this machine**, flakes enabled — no installer
  step needed here. The mac is aarch64-darwin (Apple M3 Max).
- **Q4 resolved: `mergiraf` IS in nixpkgs** (0.17.0). It moves fully into the
  flake (`home.packages`); nothing merge-related stays imperative.
- **All packages resolve and build**, including the unfree `_1password-cli`,
  which requires instantiating nixpkgs with `config.allowUnfree = true` (a
  pre-built `pkgs` ignores HM's `nixpkgs.config`).
- **HM renamed `programs.git.{userName,userEmail,extraConfig}` → `settings`**;
  git.nix uses the new `settings` form.
- **CERNET, not USTC, is the CN mirror** (the machine already had it). A
  substituter set in a *user-level* `~/.config/nix/nix.conf` is **ignored for
  non-trusted users** by the multi-user daemon; it must live in the *system*
  config (`/etc/nix/nix.custom.conf`) or the user must be in `trusted-users`.
- **New requirement (owner):** all CN mirrors (nix, brew, pypi/uv, rustup) are
  gated on `DOTFILE_NETWORK_ENV=CN`; unset → upstream defaults. Declarative
  shell vars are gated at runtime in `.zshenv`; system-level mirrors are set by
  the imperative bootstrap under the same switch.
- **fzf-tab ordering:** HM's `autosuggestion.enable` sources autosuggestions
  before the plugin list, but fzf-tab must load first. Fixed by loading
  zsh-autosuggestions as a plugin *after* fzf-tab, keeping syntax-highlighting
  last; verified in the generated `.zshrc`.

The mac host config builds green and every generated file is correct (`.zshrc`
ordering, `.zshenv` CN gate, git config with SSH signing + mergiraf +
difftastic, gitattributes, starship catppuccin_mocha theme). Remaining: Linux
container behavior test and the real-machine switch.

### 2026-07-10 — Verification round (containers + real NixOS)

The Linux path was verified end-to-end (bring up nix → seed flake input sources
from a mac-side cache to bypass CN→github → CERNET substituter → build the
aarch64-linux host → `home-manager` activate → checks):

- **Debian (aarch64 container):** 29/29 checks PASS.
- **Ubuntu (aarch64 container):** 29/29 checks PASS.
- **NixOS 25.11 (real OrbStack machine):** 28/28 checks PASS.

Every run confirmed: generated `.zshrc` orders fzf-tab < autosuggestions <
syntax-highlighting; starship catppuccin_mocha theme; git identity + mergiraf
driver + difftastic external diff; CN mirrors OFF by default and ON only under
`DOTFILE_NETWORK_ENV=CN`; all CLI binaries on the profile; interactive zsh
starts with no fatal errors; a `#!/usr/bin/env bash` project script runs from
the HM shell; mise has node+rust.

Two environmental facts (not config faults): OrbStack on Apple silicon runs
**aarch64** containers, so an `aarch64-linux` host was added; and CN **github**
flake-input fetches return 504, worked around by pre-seeding the (arch-neutral)
input sources from the mac store into each environment. Remaining: real-macOS
activation and the `platform/` imperative layer.
