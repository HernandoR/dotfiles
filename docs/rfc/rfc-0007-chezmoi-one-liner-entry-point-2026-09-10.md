# RFC-0007: Make chezmoi's own one-liner a supported second entry point

| Field | Value |
| --- | --- |
| Status | Resolved |
| Date | 2026-09-10 |
| Outcome | [ADR-0013](../plans/adr-0013-chezmoi-mise-nvm-uv-2026-09-09.md) updated 2026-09-10 (second entry point); cross-referenced in [ADR-0010](../plans/adr-0010-plan-first-one-shot-clearance-2026-08-04.md) |

## Summary

Make chezmoi's documented bootstrap

```sh
BINDIR="$HOME/.local/bin" sh -c "$(curl -fsLS https://get.chezmoi.io)" -- init --apply HernandoR
```

run to completion on a bare host, by moving the "make the bootstrap tools exist"
phase out of `scripts/bootstrap.py`'s pre-apply slot and into a chezmoi
`run_before` step that **both** entry points share. `bootstrap.sh` keeps the plan
print and the copy-aside backup unchanged; the one-liner gains the toolchain but
not the plan print, and is documented as the weaker of the two entry points.

## Motivation

The one-liner is the first thing anyone — and any agent — tries, because it is
chezmoi's own install instructions. Today it dies at the first `run_before`
script on a bare machine:

```text
env-links: uv not on PATH — run ./bootstrap.sh first
```

That message is a dead end *on the machine it is meant for*: `bootstrap.sh`
resolves `$DIR` to its own directory and is only reachable from an existing
clone, which is exactly what a bare machine does not have. Getting to
`bootstrap.sh` therefore needs `git` plus a manual `git clone` — a strictly
larger prerequisite set than the one-liner needs (a shell and `curl`).

Measured on the reference Mac, 2026-09-10:

- **The one-liner's first half already works.** Cloning the repo to
  `/tmp/fakeclone` and running `chezmoi --source /tmp/fakeclone --destination
  /tmp/cmtest/home --config /tmp/cmtest/chezmoi.toml --no-tty init` with every
  `DOTFILE_*` unset exits 0, asks nothing, and generates
  `sourceDir = "/tmp/fakeclone"` with `env=default`, `stateRoot=$HOME/dotfile_home`,
  `agents=all`, `system=default`. So `sourceDir = {{ .chezmoi.workingTree }}`
  (`home/.chezmoi.toml.tmpl:34`) keeps "the clone is the source" true for a clone
  under `~/.local/share/chezmoi` as well, and all six
  `home/.chezmoiscripts/*.sh.tmpl` address their Python through
  `{{ .chezmoi.workingTree }}/scripts/…` — none of them assumes a checkout at
  `~/Codes/dotfiles`.
- **The wall is the toolchain.** `run_before_00-env-links.sh.tmpl:6` guards on
  `uv` and exits 1; reproduced with
  `env HOME=/tmp/nohome PATH=/usr/bin:/bin sh -c '<the guard>'` → exit 1. `uv`
  is installed only by `bootstrap.sh:26`.
- **Two more of the same kind.** `mise` comes only from the `TOOLS` table
  (`scripts/bootstrap.py:83`), which `run_onchange_after_10-mise-runtimes` and
  everything after it need. Homebrew comes from `scripts/bootstrap.py:244`
  before apply, and from `scripts/components.py:266` as a *system component*
  inside apply — step 30.
- **An ordering defect that the bootstrap path hides.** On macOS the one-liner
  reaches `run_onchange_after_20-packages` with no brew, because Homebrew only
  arrives at step 30. `run_onchange_` is keyed on the hash of its inputs, so
  that script never re-runs once brew appears, and `scripts/packages.py:82`
  returns `False` for a missing brew without a warning — the brew packages stay
  missing *silently*. ADR-0013 states brew must exist before apply for exactly
  this reason; today that holds only on the bootstrap path.

A second, independent reason to move the phase rather than duplicate it: today
"which tools, from where" lives only inside `bootstrap.py`. Any other way in
(`just apply` on a host whose uv or mise was removed, a fresh container, the
one-liner) hits the same wall with no self-healing. A phase that chezmoi itself
can reach fixes all of them at once.

## Goals

- The one-liner completes on a bare macOS or Linux host that has a shell, `curl`
  and a way to clone the repo.
- One description of the toolchain: the tools step, its plan rows and its
  installs come from a single module used by both entry points (ADR-0010's
  ownership rule: the plan must not become a second, hand-maintained
  description).
- Homebrew exists *before* the first `run_onchange_after` script that needs it,
  on every entry point.
- Nothing prompts; behaviour in a pipe and under CI is unchanged.
- `./bootstrap.sh` still prints the full plan and copies existing `$HOME` files
  aside; its `--dry-run` output stays recognisably the same.

## Non-Goals

- **Restoring the plan print or the clearance prompt on the one-liner path.**
  Not achievable: `run_before` *is* part of the apply it would have to precede.
  The one-liner is a second, weaker entry point and the README will say so
  rather than implying parity.
- Making the one-liner the primary entry point. A machine that already has
  dotfiles to displace stays a `bootstrap.sh` (or `just apply`) machine.
- Replacing the imperative Python half with shell. ADR-0013 already rejected
  this: `agents.py` is reviewed logic, not shell material.

## Proposal

1. **Extract the toolchain into `scripts/tools.py`** (PEP 723, stdlib only):
   `TOOLS` (the `Script` specs), `installed_outside_nix`, `have_brew`,
   `ensure_prereqs`, `plan_tools` and `install_tools`, with a `--install` /
   `--plan` CLI. `scripts/bootstrap.py` imports it and keeps its current
   behaviour; the rows it merges into its `Plan` are the same rows as today, so
   the printed plan cannot drift from the run.
2. **One reusable shell prelude, not three.** `scripts/uv-bootstrap.sh` holds the uv
   bootstrap that `bootstrap.sh:19-30` has today (curl to a temp file, then
   `UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1 sh "$tmp"`), guarded by
   `command -v uv`. It also owns `ensure_brew_path`: when brew is present at
   `/opt/homebrew/bin/brew` or `/usr/local/bin/brew` but is not on `PATH`, it
   evaluates that binary's `shellenv`. Every chezmoi wrapper which invokes brew
   (currently packages and fonts, and any future one) sources this file and
   calls that helper before its command lookup. This is necessary because a
   `run_before` child cannot alter chezmoi's parent environment after it installs
   Homebrew. `bootstrap.sh` and the new `run_before` wrapper source the same
   file. `bootstrap.sh` remains a thin launcher; all reusable shell logic lives
   in this one prelude.
3. **New source entry `home/.chezmoiscripts/run_before_05-tools.sh.tmpl`** — a
   one-liner per the repo's convention for `.chezmoiscripts/`, delegating to
   `scripts/`:

   ```sh
   set -eu
   export PATH="$HOME/.local/bin:$PATH"
   . "{{ .chezmoi.workingTree }}/scripts/uv-bootstrap.sh"
   exec uv run --script "{{ .chezmoi.workingTree }}/scripts/tools.py" --install
   ```

   It is idempotent and cheap on a host that already has everything
   (`installed_outside_nix` per tool, then a no-op).
4. **Renumber `run_before_00-env-links.sh.tmpl` → `run_before_10-env-links.sh.tmpl`**
   so the toolchain runs first (chezmoi orders `run_` scripts lexically). Its
   own `uv` guard stays as a cheap invariant check — it can now only fire if the
   tools step failed.
5. **Take the copy-aside backup on the one-liner path too, from the same module.**
   `run_before` is genuinely before the first write, so the guarantee ADR-0010
   leans on is still reachable: `scripts/tools.py` gains a `--backup` mode that
   calls the `existing_targets` / `backup_targets` pair out of
   `scripts/bootstrap.py` into `~/dotfiles_backup/<stamp>/`. It records a
   first-apply **pending** marker only after that backup completes. A new final
   `run_after` source entry atomically promotes pending to `first-apply.done`;
   it runs only after the whole apply succeeds. A failed apply therefore leaves
   pending (and its backup) for the retry, never a false done marker. To avoid
   two backups per bootstrap run, `bootstrap.py` exports a marker (the
   `DF_ASSUME_YES` pattern) and the tools step records pending without taking a
   second copy. **Open question 1 decides whether this ships in the same change.**
6. **Fix the brew ordering defect at its root.** With (3) brew is installed before
   apply on every path, and `ensure_brew_path` makes it resolvable by the package
   and font wrappers even on a fresh Apple Silicon host. Additionally
   `scripts/packages.py` must *warn* instead of silently returning `False` when
   the host is macOS, `packages.toml` has brew entries, and brew is missing — so
   "ran, installed nothing, will never re-run" cannot recur unnoticed.
7. **Document the invocation, including its sharp edges.** README "Quick start"
   gains the one-liner as the bare-machine path with the honest caveat (no plan
   print; run `just diff` afterwards), and records why `BINDIR` is an
   environment variable rather than `-b`: the installer's `getopts` stops at the
   first non-option argument (`init`), so a `-b` after it is forwarded to
   chezmoi itself; without `BINDIR` the binary lands in the caller's `./bin`
   (upstream default `BINDIR="${BINDIR:-bin}"`), contradicting ADR-0013's
   "self-installed tools live in `~/.local/bin`". The `get.chezmoi.io/lb`
   variant (defaults to `.local/bin`, i.e. relative to the cwd) is mentioned as
   the alternative, with the "run it from `$HOME`" caveat.
8. **Guard the new ordering contract in `scripts/check.py`.** The `run_before`
   numbering is now load-bearing: add an assertion that every
   `.chezmoiscripts/run_*.sh.tmpl` which invokes `uv`, `mise` or `brew` is
   preceded by the step that guarantees it, and that each brew caller invokes
   the shared PATH helper first. A future `run_before_03-*` that needs the
   toolchain then fails `just check` instead of failing on a fresh host.

## Alternatives Considered

| Alternative | Why not |
| --- | --- |
| Give each `run_` script its own prerequisite prelude (uv in `run_before_00`, mise inside `runtimes.py`, brew inside `packages.py`) | Same call sites, but "which tools, from where" is then spread over three files unless `tools.py` is extracted anyway — and ADR-0010's rule is that the plan and the run share one description. Kept only as the `packages.py` warning in Proposal 6. |
| A repo-owned remote launcher: a curl-able `scripts/remote.sh` that clones and `exec`s `bootstrap.sh` | Keeps one entry point and leaves ADR-0010 fully intact, at the cost of *not* being the chezmoi-documented command. Recorded as the fallback if the "weaker second entry point" is judged unacceptable. |
| Do nothing; document "clone first, then run `bootstrap.sh`" | The bare machine has no clone, and getting one needs `git` (absent on a fresh macOS without the command line tools) — a larger prerequisite set than the one-liner. The ordering defect in Motivation stays too. |
| Ship chezmoi via mise | Does not help: `uv` is the first wall, and mise is installed by the same phase. |
| Move the toolchain into a chezmoi `run_onchange_` script instead of `run_before` | `run_before` is the only phase that provably precedes the first script that needs `uv`; `run_onchange_` cannot run before `run_before`. |

## Risks

- **Two entry points, one without the plan.** Mitigated by documentation and by
  keeping `bootstrap.sh` the recommended path wherever the machine has data to
  displace. Not fully mitigable: this is the price of supporting the one-liner.
- **New shell prelude.** Mitigated by Proposal 2: `bootstrap.sh` remains a thin
  launcher and `uv-bootstrap.sh` is the one reusable shell implementation shared
  with chezmoi's script phase.
- **Ordering becomes a contract.** `run_before_05` vs `run_before_10` is now
  load-bearing. Mitigated by Proposal 8.
- **Nested `chezmoi status`** (the backup in Proposal 5) runs while chezmoi is
  already applying. Reentrancy is unproven; if it misbehaves on either OS the
  backup becomes a follow-up change and the one-liner ships without it.
- **An interrupted first apply must not look complete.** The pending/done
  transaction in Proposal 5 leaves the retry eligible for the tools step while
  preserving its first backup; its promotion is deliberately a separate final
  `run_after` action, never work attempted by the `run_before` child.
- **Idempotence relies on `installed_outside_nix`.** A Nix-era `uv`/`mise` is
  reinstalled by design, so a migration host pays the download twice. Unchanged
  from today on the bootstrap path; now it also applies on a plain `just apply`.
- **Two chezmois.** Without `BINDIR`, the one-liner's binary lives in `./bin` and
  `just update`'s `chezmoi upgrade` upgrades whichever is on PATH. Documented in
  Proposal 7; not enforced by code.

## Open Questions

All four were answered on 2026-09-10 — see [Decision log](#decision-log-2026-09-10)
below. The list is left as written.

1. Does the one-liner take the copy-aside backup in this change (Proposal 5), or
   is "bare machine, little to displace" good enough to defer it? The owner's
   call, and it decides whether `tools.py --backup` ships now.
2. Should the tools step run on *every* apply (one `uv run` of Python startup)
   or be skipped by a cheap shell fast-path when `uv`, `mise`, `chezmoi` and
   (macOS) `brew` all resolve? The fast path is faster but restates the tool
   inventory in shell — the opposite of "data over code".
3. Is `chezmoi apply --exclude scripts` still appropriate for the one-liner
   documentation examples, given that `run_before` is a script?
4. Does the fallback in Alternatives (the repo-owned remote launcher) deserve to
   ship *as well*, as the primary bare-machine command, with the one-liner
   supported afterwards?

## Acceptance Criteria

- [ ] On a container with a throwaway `$HOME` and no `uv`/`mise`/`brew`/`chezmoi`:
      `BINDIR="$HOME/.local/bin" sh -c "$(curl -fsLS https://get.chezmoi.io)" -- init --apply HernandoR`
      exits 0; `uv`, `mise` and `chezmoi` all resolve inside `~/.local/bin`; a
      second `chezmoi apply` changes nothing in the tools step.
- [ ] On a fresh Apple Silicon macOS host the same run has `brew` on PATH before
      `run_onchange_after_20-packages` and `run_onchange_after_25-fonts` run
      (asserted from a `--verbose` apply log), and the brew packages from
      `packages.toml` are present afterwards.
- [ ] `scripts/packages.py` warns, not silently skips, when brew entries exist
      on macOS without brew.
- [ ] `./bootstrap.sh --dry-run` output differs only by the new and renumbered
      `run_before` script names; its plan rows still come from the shared module.
- [ ] `just check` passes, including the new `run_before` ordering assertion.
- [ ] README states the one-liner's handicap (no plan print) in the same section
      that introduces it.
- [ ] A deliberately failing first apply leaves a pending marker, no done marker,
      and a byte-preserving backup of a pre-existing managed file. Retrying after
      removing the failure completes the apply and atomically promotes pending to
      done without making a second backup.

## Rollout

1. Extract `scripts/tools.py` and `scripts/uv-bootstrap.sh` with no behaviour
   change; `bootstrap.sh` sources the latter, `bootstrap.py` imports the former.
   Compare `./bootstrap.sh --dry-run` before and after this step.
2. Add `home/.chezmoiscripts/run_before_05-tools.sh.tmpl`; renumber
   `run_before_00-env-links` to `_10`; add the final `run_after` stamp promoter.
   Source the shared brew-PATH helper from every wrapper that calls brew.
3. Add the `packages.py` warning (Proposal 6) and the `check.py` ordering
   assertion (Proposal 8).
4. Decide Open Question 1; if yes, add `tools.py --backup` plus the
   double-backup marker.
5. README + the ADR-0013 atomic edit (the "only shell" line, and a sentence
   naming the one-liner as the second entry point) + an ADR-0010 cross-reference
   recording that its plan print does not exist on that path.
6. Acceptance run on a container, then on macOS.

**Rollback:** delete `run_before_05-tools.sh.tmpl`, restore the `_00` name, and
revert the `bootstrap.py` import; `bootstrap.sh` is otherwise untouched, so the
repo returns to today's behaviour with the shared modules still in place.

## Decision log (2026-09-10)

Answered by the owner after review. This section amends the proposal; the
sections above are left as written, because an RFC is a discussion log and not
a spec.

1. **The copy-aside backup ships in this change** (closes Open Question 1).
   `tools.py` gains `--backup`, reusing `existing_targets` / `backup_targets`
   from `scripts/bootstrap.py`.
2. **The fast path ships** (closes Open Question 2): when every tool `tools.py`
   declares already resolves, the wrapper skips the Python step. The inventory
   is not restated by hand — `scripts/check.py` asserts the shell list equals
   the `TOOLS` keys (+ `brew` on darwin), so "data over code" survives the
   check.
3. **`--exclude scripts` leaves anything user-facing** (closes Open Question 3 —
   resolved here, not by the owner). Verified 2026-09-10 against a two-entry
   probe source: `chezmoi apply --dry-run` executes no `run_` script and writes
   nothing, so a preview needs no exclusion at all; and excluding `scripts` from
   a *real* first apply would skip `run_before` — i.e. exactly the toolchain and
   the env links that apply exists for. `-x/--exclude` stays only where the
   caller already describes those steps itself: `scripts/bootstrap.py:337` and
   `:672` (its own plan and scratch diff) and `scripts/check.py:137` (the render
   check must not run the imperative half). The README's one-liner section tells
   the reader to preview with `chezmoi apply --dry-run`.
4. **No repo-owned remote launcher** (closes Open Question 4): the fallback in
   *Alternatives Considered* is dropped. The one-liner is the bare-machine path;
   `bootstrap.sh` stays the recommendation wherever there are files to displace.
   Consequence: ADR-0010's plan print remains a bootstrap-path property, and
   that ADR now records it.

### Amendments to the proposal

- **Proposal 3 gains the fast path, and it must not swallow the backup.** The
  tools step takes the backup only when the machine has neither a completed nor
  a pending first-apply transaction:

  ```sh
  set -eu
  export PATH="$HOME/.local/bin:$PATH"
  . "{{ .chezmoi.workingTree }}/scripts/uv-bootstrap.sh"
  ensure_brew_path
  if tools_present && [ -e "$HOME/.local/state/dotfiles/first-apply.done" ]; then
    exit 0
  fi
  exec uv run --script "{{ .chezmoi.workingTree }}/scripts/tools.py" --install --backup
  ```

  `tools_present` lives beside the uv bootstrap (one shell file), normalizes brew
  with `ensure_brew_path`, and covers every declared tool plus `brew` on darwin.
  A bootstrap run exports `DF_BACKUP_TAKEN=1` once its own backup is taken (the
  `DF_ASSUME_YES` pattern), so the nested apply takes neither a second backup nor
  a second tool pass. `tools.py` creates
  `~/.local/state/dotfiles/first-apply.pending` only after its backup succeeds;
  `run_after_99-first-apply-stamp` atomically renames it to `.done` after every
  other apply action succeeds. The `run_before` child never writes `.done`: it
  cannot observe the parent apply's result. A retry with pending reuses the
  preserved backup and retries the tools step; only `.done` enables the fast
  path. That is what keeps a plain `just apply` from dropping a
  `~/dotfiles_backup/<stamp>/` on every run while still giving the one-liner the
  same once-per-machine guarantee. Accepted consequence: the *first* apply after
  this change takes one backup on a machine that never had one.
- **Proposal 5 is no longer conditional**: `tools.py --backup` ships, with the
  marker and stamp above.
- **Proposal 7 stands**, minus the remote launcher.
- **This RFC is Resolved.** The outcome is an atomic edit of
  [ADR-0013](../plans/adr-0013-chezmoi-mise-nvm-uv-2026-09-09.md) — the "only
  shell" line, the toolchain paragraph, a new "two entry points" statement and
  the layout table — plus the cross-reference recorded in
  [ADR-0010](../plans/adr-0010-plan-first-one-shot-clearance-2026-08-04.md).

## Appendix: 中文译本 (reading transcript)

English wins on any disagreement; this section exists only as a reading aid.

**摘要** —— 让 chezmoi 官方那条 `sh -c "$(curl -fsLS https://get.chezmoi.io)"
-- init --apply <user>` 在裸机上跑通：把"让 bootstrap 工具存在"这一步从
`bootstrap.py` 的 apply 之前搬进 chezmoi 的 `run_before`，两条入口共用同一份代码。
`bootstrap.sh` 的计划打印与备份不变；one-liner 拿到工具链，但没有计划打印，README
会如实标注它是较弱的入口。

**动机** —— 今天 one-liner 在第一个 `run_before` 就死：
`env-links: uv not on PATH — run ./bootstrap.sh first`。而这台机器上根本没有
clone 可供 `bootstrap.sh` 使用，要 clone 又需要 `git`（全新 macOS 上没有命令行
工具就没有 git）——比 one-liner 所需的前置条件更多。实测（2026-09-10）：init 那
半段已经能跑通（无提问、`sourceDir` 指向 clone、默认值齐全），六个 run_ 脚本都
通过 `{{ .chezmoi.workingTree }}` 定位 Python；缺的只有工具链（uv 来自
`bootstrap.sh:26`，mise 来自 `bootstrap.py:83`，brew 来自 `bootstrap.py:244`）。
另外发现一个顺序缺陷：macOS 上 `_20-packages` 跑在 brew 之前，而
`run_onchange_` 按哈希触发、不会再跑，`packages.py:82` 又静默返回 False —— brew
包会一直悄悄缺失。

**提案** —— 抽出 `scripts/tools.py` 与 `scripts/uv-bootstrap.sh`（两份入口共用一
份 shell）；后者还统一把新装的 Homebrew 加入 `PATH`，供 packages / fonts 等脚本
复用。新增 `home/.chezmoiscripts/run_before_05-tools.sh.tmpl`；
`run_before_00-env-links` 改名为 `_10`；另加最后执行的 `run_after`，只在整个
apply 成功后把首次 apply 的 pending 标记原子提升为 done。`packages.py` 在缺 brew
时改为告警；`check.py` 增加"run_before 顺序和 brew PATH helper"断言；README 记录
one-liner 的短板与 `BINDIR` 的用法（`-b` 无法在 `init` 之后传入，否则 chezmoi 会
落到 `./bin`）。

**非目标** —— 不试图在 one-liner 路径上恢复计划打印/清关（`run_before` 本身就在
apply 里面，做不到）；不让 one-liner 成为首选入口。

**开放问题** —— 是否在同一变更里带上备份步骤；工具步骤要不要加 shell 快速路径；
是否同时提供仓库自己的远端启动器作为裸机首选命令。

**决定（2026-09-10）** —— 1) 备份同批做，`tools.py --backup`；备份成功才写 pending，
仅完整 apply 成功后的 `run_after` 才把它提升为 done，失败重试会复用原备份；2) 快速路径
做：声明的工具都在且 done 存在才跳过 Python 那一步（清单不手写，由 `check.py` 断言与
`TOOLS` 一致）；
3) `--exclude scripts` 从面向用户的说明里去掉 —— 实测 `chezmoi apply --dry-run` 不执行
任何脚本、不写任何文件，预览本就不需要排除；而真跑时排除 scripts 会跳过 `run_before`，
也就是跳过工具链和 env links，`-x` 只保留在 bootstrap.py / check.py 这些自己会描述
这些步骤的内部调用里；4) 不做仓库自己的远端启动器。备份用 pending/done 事务保证一台
机器只做一次，`bootstrap.py` 导出标记避免嵌套 apply 重复备份。
