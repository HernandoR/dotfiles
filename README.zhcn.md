# lz 的 dotfiles

> 本文档是 [README.md](README.md) 的中文翻译版；如与英文版有出入，以英文版为准。

跨平台 dotfiles，基于 **Nix flake + 独立
[Home Manager](https://nix-community.github.io/home-manager/)**，运行在
[**Lix**](https://lix.systems/) 之上，并附带一层轻量的**命令式层**
（[`platform/`](platform/)），用于处理 Home Manager 在非 NixOS 主机上无法完成的少数事项。
目标平台为 macOS（aarch64）和 Debian/Ubuntu（x86_64 + aarch64）。
zsh + Starship（catppuccin_mocha）+ fzf-tab 的使用体验被完整保留。

设计记录见 [ADR-0007](docs/plans/adr-0007-nix-home-manager-migration-2026-07-09.md)
（意图）与 [RFC-0001](docs/rfc/rfc-0001-nix-home-manager-migration-2026-07-09.md)
（讨论过程）；[AGENT.md](AGENT.md) 是贡献者/agent 指南。

> **警告：** 这些是我的个人配置。请先 fork 本仓库并审阅代码，再运行它——不要盲目套用别人的配置。
> bootstrap 可能会安装 Nix、更改你的登录 shell，并安装系统软件。请先阅读
> **[在新机器上试用（以及如何恢复）](#在新机器上试用以及如何恢复)** 了解（完全可恢复的）安全模型。

## 快速开始

```bash
git clone git@github.com:HernandoR/dotfiles.git
cd dotfiles
./bootstrap.sh --dry-run --verbose   # 预览每一步，什么都不执行（建议先跑这个）
./bootstrap.sh                       # 然后再真正执行
```

`bootstrap.sh` 需要 `curl` 和 `git`。如果 Nix 已安装则无需任何权限；
否则需要 root/sudo 来安装 Lix（在没有 init 系统的裸容器/CI 中，会回退到单用户安装）。

## bootstrap 做了什么

以 Home Manager 切换为界一分为二：

1. **HM 之前（shell）：** 检测权限（root / sudo / 无）→ 安装前置依赖 →
   **安装 Lix** → 配置 Nix（+ 可选的 CERNET 镜像）→
   **构建并激活 Home Manager**（使用 `-b backup`）。
2. **HM 之后（通过 `uv` 运行 Python）：** 把登录 shell 设为 Nix 的 zsh（`chsh`）→
   部署 SSH 密钥 → 写入延迟执行的 Claude 配置 → 安装任意可选的 Linux 系统组件。

执行完成后，启动它的那个 shell 仍保留**旧的** PATH，因此直接输入 `zsh` 还找不到。
用它打印出来的绝对路径启动新环境，或者直接重新登录（你的登录 shell 已经是 zsh）：

```bash
exec ~/.nix-profile/bin/zsh -l
```

## 参数与环境变量

| 参数 | 效果 |
| --- | --- |
| `--dry-run` | 打印每条命令但不执行。 |
| `--verbose` | 执行时回显每条命令。 |
| `--network CN` | 为 Nix、pypi/uv 和 rustup 启用中国（CERNET）镜像。 |
| `--system <list>` | 安装可选的 Linux 系统组件（`all` = 全部）。 |
| `--host NAME` | 强制使用指定的 flake host，而非自动检测。 |
| `--no-claude` | 跳过写入 Claude/Lark/MCP 的后置配置。 |

| 环境变量 | 效果 |
| --- | --- |
| `DOTFILE_NETWORK_ENV=CN` | 等同于 `--network CN`（zsh 环境也会读取它用于 pypi/rustup）。 |
| `DOTFILE_SYSTEM_COMPONENTS` | `--system` 的回退值（如 `all`）；参数优先。 |
| `DOTFILE_FLAKE_CACHE` | 含 `seed-paths.txt` 的目录，用于给 flake 输入做种（CN/离线/CI）。 |
| `DOTFILE_SSH_SRC` | 覆盖 SSH 密钥源目录（默认 `sources/root/.ssh`）。 |
| `DOTFILE_HOME_LINK_SRC` | 可选：将该目录下的每个直接子文件夹软链接到 `$HOME`。若 `~/<名称>` 已是真实文件/目录，先备份为 `~/<名称>.pre-dotfiles.bak`（若已存在则依次 `.bak.1`、`.2`…）。未设置则跳过。 |

## 在新机器上试用（以及如何恢复）

**安全模型——不会破坏任何东西：**

- **先预览：** `./bootstrap.sh --dry-run --verbose` 什么都不执行。
- **已有的 dotfiles 会被备份，而不是删除。** 激活使用 `-b backup`
  （`HOME_MANAGER_BACKUP_EXT=backup`），因此已存在的 `~/.zshrc` /
  `~/.gitconfig` 等会在放置 Home Manager 软链接前被重命名为 `~/.zshrc.backup`。
- **旧的配置保持不变。** 本套配置位于 `feat/lix-based` 分支；
  之前的配置仍在 `main` 分支，且之前的 Home Manager generation 在你手动清理前一直保留。

**回滚（在 `home-manager` CLI 进入 PATH 之后）：**

```bash
# 1) 精确回退一个 generation（无需重建、无需 flake）
home-manager switch --rollback

# 2) 或激活某个更早的 generation
home-manager generations                                   # 列出（最新在前）
PROFILE=~/.local/state/nix/profiles/home-manager           # 或 /nix/var/nix/profiles/per-user/$USER/home-manager
nix-env --profile "$PROFILE" --switch-generation <id>
"$PROFILE"/activate

# 3) 恢复一个被备份的文件
mv ~/.zshrc.backup ~/.zshrc                                # 对任意 *.backup 重复此操作

# 4) 恢复你之前的登录 shell
chsh -s "$(command -v bash)"                               # 或你之前的 shell
```

**彻底卸载 Home Manager：**

```bash
home-manager uninstall        # 会提示确认；移除 HM 软链接 + generation
```

`uninstall` 会移除 Home Manager 创建的软链接，但**不会恢复你的 `*.backup` 文件**——
需手动移回（`mv ~/.zshrc.backup ~/.zshrc`）并 `chsh` 回你之前的 shell。
用 `nix-collect-garbage -d` 回收存储空间。要彻底移除 Nix/Lix，请按 Lix 卸载文档操作。

**日后清理旧的 generation：**

```bash
home-manager expire-generations "-30 days"   # 保留最近 30 天（当前的始终保留）
home-manager remove-generations <id> [<id>…] # 移除指定的若干个
nix-collect-garbage -d                        # 然后回收磁盘
```

## 可选系统组件

用户级工具始终以声明式方式安装（见
[home/packages.nix](home/packages.nix)）。*系统级*软件通过
`--system` 或 `DOTFILE_SYSTEM_COMPONENTS` 选择（参数优先）。特殊取值：`all`
（全部组件；若两个 Docker 变体同时匹配，则 **rootless 胜出**）、`default` 和 `none`。

在 debian/ubuntu 上，`software-properties` 是**必需组件**：它提供
`add-apt-repository`（docker/nvidia/llvm 配置软件源的前置依赖），因此无论你选了
什么，它都会一并安装 —— `--system docker` 也会顺带装上 `software-properties`。
只有 `--system none` 会跳过它。

**当你什么都不传时，安装 `default` 组** —— macOS 上是 `brew`（Linux 上则是必需的
`software-properties`）。其余都是按需 opt-in；`cuda`/`nvidia`/`llvm`/`docker`
需要你显式请求。每个组件都受其 OS 约束，因此一个 spec 只会安装适用于本主机的部分。

```bash
./bootstrap.sh                       # 必需 + default（Linux 上 software-properties / macOS 上 brew）
./bootstrap.sh --system docker,llvm  # 这些 + 必需的 software-properties
./bootstrap.sh --system all          # 适用于本 OS 的全部组件
./bootstrap.sh --system none         # 完全不装系统组件（连必需组件也跳过）
DOTFILE_SYSTEM_COMPONENTS=cuda,nvidia ./bootstrap.sh
```

要在 bootstrap **之后**添加组件，有一个手动交互式选择器（不会自动运行）——
它以清单形式列出适用于本 OS 的组件（default 组预先勾选），允许你切换本次运行的网络，
然后通过同一套机制安装：

```bash
./nix-system-interactive-install.sh            # 选择 + 安装
./nix-system-interactive-install.sh --dry-run  # 仅预览
```

| 名称 | 描述 | OS |
| --- | --- | --- |
| `software-properties` | `add-apt-repository` 支持 **（Linux 必需 —— 始终安装）** | debian, ubuntu |
| `docker` | Docker Engine（rootful） | debian, ubuntu |
| `docker-rootless` | Docker（rootless） | debian, ubuntu |
| `cuda` | CUDA Toolkit 12.6 | debian, ubuntu |
| `nvidia` | NVIDIA 驱动 + container toolkit | debian, ubuntu |
| `llvm` | LLVM 18（+ `update-alternatives`） | debian, ubuntu |
| `brew` | Homebrew —— 仅包管理器本身（不含 formulae/casks）**（macOS 默认）** | darwin |

在 macOS 上，bootstrap **默认不**安装 Homebrew（CLI 工具来自 nixpkgs）。
用 `--system brew`（或 `--system all`）添加它；在 CN 环境会使用 BFSU 镜像。
它只安装 Homebrew *本身*——GUI 应用请自行用 `brew install --cask <app>` 添加。

对于 GUI 应用，有一个手动的**交互式 cask 选择器**（不会自动运行）：

```bash
./brew-cask-interactive-install.sh
```

它运行一个小的 `uv` 脚本（[platform/brew_cask_install.py](platform/brew_cask_install.py)，
依赖以 uv script 模式内联声明），将推荐的 cask 以清单形式展示（Edge + Alacritty
预先勾选——在文件里编辑列表），允许你为本次运行选择一个 Homebrew 镜像
（默认跟随 `DOTFILE_NETWORK_ENV`），然后安装你的选择。

随时列出它们：`uv run platform/installers/components.py`。

## 登录后交互式配置

Claude/Smithery/Lark 配置（插件、MCP 服务器、Lark CLI 认证）是*交互式*的，
因此**不会**自动运行。`setup.py` 会把它写到
`~/.local/share/dotfiles/post-login-setup.sh`；在其待执行期间，zsh 会打印一条提示。
当你准备好授权时，运行一次：

```bash
dotfiles-postsetup    # 需要 TTY；成功后自删除
```

**Smithery MCP。** [Smithery](https://smithery.ai/) CLI 预期已经安装好，
因此脚本直接调用 `smithery`（无需 `npx`）。它会：

1. **API Key 认证** —— 如果环境中设置了 `SMITHERY_API_KEY`，会询问是否用该 key 认证。
   CLI 自身会读取该变量，所以选择「是」只是通过 `smithery auth whoami` 验证一下；
   若未设置该 key，则改为提供交互式的 `smithery auth login`。
2. **命名空间（namespace）形式** —— 随后询问是否把你命名空间的聚合 MCP 端点
   （`https://mcp.smithery.run/<namespace>`）通过 `smithery mcp add … --client claude`
   添加到 Claude，失败则回退到
   `claude mcp add --transport http <namespace> https://mcp.smithery.run/<namespace>`。
3. 留下一行**已注释**的 `smithery mcp add <server> --client claude`
   （如 `upstash/context7-mcp`，它已包含在命名空间内），作为日后添加独立服务器的模板。

## 中国镜像

所有与镜像相关的开关都集中在一个总开关上。设置 `--network CN`（或
`DOTFILE_NETWORK_ENV=CN`）后，bootstrap 会把 CERNET substituter 写进系统
`nix.conf`，zsh 则导出 pypi/uv + rustup 镜像。不设置 = 上游默认源。

## 仓库布局

```text
bootstrap.sh      精简入口 → platform/bootstrap.sh
flake.nix         Inputs（nixpkgs + home-manager）、hosts、homeConfigurations
home/             Home Manager 模块——声明式的用户环境
  packages.nix    所有用户级 CLI 工具
  shell.nix       zsh（fzf-tab 顺序）、fzf、zoxide、sessionPath/Variables
  starship.nix    + starship.toml（catppuccin_mocha 主题）
  git.nix, tmux.nix, mise.nix, zsh/
platform/         命令式层（见 platform/README.md）
  bootstrap.sh    编排器；lib.sh；nix-cn.sh；setup.py；installers/
docs/plans/       ADR（0007 为准）
docs/rfc/         RFC（0001 = 迁移日志）
sources/          遗留资产（不由 Home Manager 部署）
```

## 说明

- **运行时：** node/rust 通过 [mise](https://mise.jdx.dev/)，Python 通过
  [uv](https://docs.astral.sh/uv/)。Nix **不**提供系统级 Python。
- 请在克隆下来的仓库内部运行 bootstrap。
