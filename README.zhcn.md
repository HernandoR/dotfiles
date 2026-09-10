# lz 的 dotfiles

跨平台 dotfiles：**[chezmoi](https://www.chezmoi.io/)** 管文件，
**[mise](https://mise.jdx.dev/)** 管运行时和绝大部分 CLI 工具（预编译发布二进制），
**[nvm](https://github.com/nvm-sh/nvm)** 管 Node 生态，其余命令式步骤（包括通过
brew / apt / dnf / yum 安装的少数系统级软件包）由若干 **`uv run` Python 脚本**完成。目标平台：macOS (aarch64) 与 Debian/Ubuntu (x86_64 + aarch64)。
zsh + Starship (catppuccin_mocha) + fzf-tab 的体验不变。

完整手册见英文 [README.md](README.md)；设计记录见
[ADR-0013](docs/plans/adr-0013-chezmoi-mise-nvm-uv-2026-09-09.md) 与
[RFC-0006](docs/rfc/rfc-0006-chezmoi-zoi-mise-uv-2026-09-09.md)。
上一代（Nix + Home Manager）保留在 `archive/homemanager/*` 分支。

> **警告：** 这是我的个人配置。Fork 并审阅代码后再运行。bootstrap 会安装工具、
> 修改登录 shell、覆盖 dotfiles（覆盖前会先把原文件复制到
> `~/dotfiles_backup/<时间戳>/`）。

## 快速开始

```bash
git clone git@github.com:HernandoR/dotfiles.git
cd dotfiles
./bootstrap.sh --dry-run --verbose   # 预览每一步，不做任何改动（推荐先跑）
./bootstrap.sh                       # 正式运行
```

只需要 `curl` 和 `git`。用户层（uv、chezmoi、mise，全部装进 `~/.local/bin`）
不需要 root；root/sudo 只用于缺失的前置依赖、`chsh` 以及可选的系统组件。

它会先打印完整计划——安装什么、写入/链接哪些文件、会复制备份哪些现有文件——
然后**直接执行，不询问**（ADR-0010）。因为它通常运行在 CI、容器构建、devpod 重建
或 agent 的 shell 里，任何提问都会把整个流程挂住。想先看不想执行就用 `--dry-run`；
想恢复确认提示和 `chezmoi init` 的提问，加 `--interactive`。保护你数据的是"先复制
备份"，不是那个提示。

## bootstrap 做了什么

1. **工具：** 检测权限 → 安装前置依赖 → macOS 上安装 Homebrew（系统级软件包和字体
   需要它）→ 用各自的安装脚本安装 chezmoi、mise（先下载再执行，绝不 `curl | sh`）。
   uv 已由 `bootstrap.sh` 用同样方式装好，因为脚本本身跑在它提供的 Python 上。这三个
   是 mise 不管的工具，`just update` 会原地升级它们。
2. **`chezmoi init`：** 记录本机答案 `env` / `stateRoot` / `network` / `agents` /
   `system`（来自 `home/.chezmoi.toml.tmpl`；命令行参数或 `DOTFILE_*` 环境变量可
   无人值守地回答）。仓库本身就是 chezmoi 的 source 目录。
3. **备份：** apply 会改动的所有现有 `$HOME` 路径先复制到
   `~/dotfiles_backup/<时间戳>/`。
4. **`chezmoi apply`：** 先运行 env links（`scripts/env_links.py`，持久化的
   `$HOME` 软链：`~/.claude`、`~/.ssh`、`~/.exports` 等），再写入 `home/` 下的文件与
   zsh 插件，最后按需运行 mise 工具（`scripts/runtimes.py`）、nvm/Node
   （`scripts/node.py`）、系统级软件包（`scripts/packages.py`）、字体、
   `scripts/setup.py`（登录 shell、agent 工具链、系统组件）。

## 常用命令

| 命令 | 作用 |
| --- | --- |
| `--env NAME` | 环境：`default` / `mewtant` / `ec2-wo-fsx`（取代原 `prod/*` 分支） |
| `--network CN` | 中国镜像（pypi/uv、rustup、Homebrew 安装器） |
| `--agents <list>` | 要配置的编码 agent：`claude,codex,pi` / `all` / `none` |
| `--system <list>` | 可选 Linux 系统组件（`all` / `none` / 名称列表） |
| `--interactive` / `-i` | 运行前询问，并让 `chezmoi init` 提问（默认全程无人值守） |
| `just diff` / `just apply` / `just status` | 查看差异 / 应用 / 逐文件状态 |
| `just check` | 校验仓库：数据文件、脚本、每个环境的完整渲染 |
| `just update` | `git pull` + apply + 原地升级 uv/chezmoi/mise + `mise up` |

## 从 Nix + Home Manager 迁移

直接运行 `./bootstrap.sh`。它会在旧环境仍然存在的情况下装好新一代，`chezmoi apply`
接管 Home Manager 原本拥有的文件，所以在移除任何东西之前机器就已经可用。注意：
bootstrap 把位于 `/nix` 下的工具视为**未安装**，会另装一份到 `~/.local/bin`，因为
Nix 的那一份会随 Nix 一起消失。

之后残留的是 Home Manager 指向 `/nix/store` 的 `$HOME` 软链、`~/.local/state` 下的
profile，以及 Nix 的 store 与 daemon。清理它们是一次性的手工活，这里刻意不做自动化：
安全的部分只是删除指向 `/nix` 的软链（绝不删真实文件，也绝不进入 `~/dotfile_home`
和 `~/dotfiles_backup/`），其余取决于当初是哪个安装器装的 Nix。Determinate / Lix
安装器装的可以用 `sudo /nix/nix-installer uninstall` 自行卸载；经典 nixos.org 脚本
装的则要按 [NixOS 手册](https://nix.dev/manual/nix/stable/installation/uninstall)
手工处理，最后一步是删除 APFS store 卷并重启。

## 分层与归属

- **仓库拥有的文件**（`home/dot_*`）：chezmoi 每次 apply 都会写回；工具会在运行时
  改写的文件**永远不能**放在这里。
- **持久可变状态**（`home/.chezmoidata/envlinks.toml`）：`$HOME` 下指向本机
  `stateRoot` 的软链，只在首次创建时播种；若某个工具把软链替换成了普通文件，
  `env_links.py` 会把它折回目标并恢复链接。
- **工具与运行时**（`mise.toml`）：绝大部分 CLI 工具走 mise 的 aqua/ubi/cargo/vfox/conda
  后端（conda 后端由 mise 自己解析下载，不会装 conda 二进制）。`runtimes.py` 只把仓库
  声明而本机 `config.toml` 缺少的工具用 `mise use -g` 加进去，已有的版本一律保留。
- **Node 生态**（`node.toml`）：nvm，不走 mise。`node.py` 安装 nvm、Node LTS、pnpm 与
  全局 npm 包；交互式 zsh 加载 `nvm.sh`，其他进程由 `env.zsh` 把最新已装 Node 放上 PATH。
- **系统级软件包**（`packages.toml`）：只剩 zsh、GNU 工具、git、vim、wget、rsync、tree、
  xclip 这类必须由系统包管理器提供的。`packages.py` 自动探测 brew / apt / dnf / yum。

### 机器本地的“逃生口”

`~/.path`、`~/.exports`（每个 zsh 都会读取，`.zshenv` 与 `.zprofile` 各读一次，
所以能覆盖仓库设置并把 PATH 放到最前）、`~/.proxy`、`~/.extra`（交互式 zsh 最后
读取）。它们位于 stateRoot 上、被软链进 `$HOME`，仓库只负责创建，从不改写。

## 添加软件

- CLI 工具、运行时 → `home/.chezmoidata/mise.toml`（mise 能装的都放这里；
  `just runtimes` 会把新增的加到每台机器）。
- Node 包 → `home/.chezmoidata/node.toml`。
- 必须由系统包管理器提供的 → `home/.chezmoidata/packages.toml`
  （brew / apt / dnf 各一个名字，没有的写 `""`）。
- 需要持久化的 `$HOME` 路径 → `home/.chezmoidata/envlinks.toml`。
- 普通 dotfile → `home/`（`chezmoi add ~/.config/tool/config`）。
- 系统组件 / agent 能力 → `scripts/components.py` / `scripts/agents.py`。

## 验证

没有测试框架。`just check` 运行 `scripts/check.py`：校验三个数据文件、编译并
`--help` 每个脚本、按环境把整棵树渲染进临时 `$HOME` 并用 `zsh -n`、
`git config --list`、TOML 解析检查结果。`./bootstrap.sh --dry-run --verbose`
展示完整计划与 chezmoi 的 diff。

## 交互

**默认全程无人值守。** `just apply`、chezmoi 执行的每个 `run_` 脚本、以及手动运行的
各个脚本都不会提问；`just init` 是唯一会提问的 recipe（重新回答本机的那五个问题正是
它的用途）。只有两处仍会等待输入，都是刻意为之且不在 bootstrap 路径上：
`dotfiles-postsetup`（OAuth 登录确实需要人）和 `./brew-cask-interactive-install.sh`
（手动勾选）。此外 `sudo` 在需要时仍可能索要密码。
