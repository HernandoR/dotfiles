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

**在终端里运行时，它会先问过你再动手。** 它会先打印完整计划——将安装什么、
用哪个网络/镜像、写入哪些配置文件、放置哪些软链接——然后**一次性**征求许可：

```text
==> Plan — nothing has run yet
  os          ubuntu (x86_64)
  host        dotfiles-debian
  privilege   sudo — privileged steps run via sudo (may ask for your password)
  network     upstream defaults (pass --network CN for the China mirrors)

  will install
    - prerequisites via apt-get: curl git xz-utils ca-certificates   [privileged]
    - Lix (multi-user) — fetch install.lix.systems/lix, create /nix, …   [privileged]
    - Home Manager generation for 'dotfiles-debian' — the whole user environment …
    - mise runtimes: aws-cli, docker-cli, go, just, node, …

  will write / link
    - /etc/nix/nix.conf <- experimental-features = nix-command flakes   [privileged]
    - Home Manager symlinks into /home/lz from the nix store (~/.zshrc, ~/.config/git, …)
    - link map ~/link-map.jsonc: 7 entries, 1 of them displacing a real file/dir
    - login shell /bin/bash -> ~/.nix-profile/bin/zsh (chsh; adds it to /etc/shells)   [privileged]

  will move your existing files aside (renamed, never deleted)
    - any $HOME file Home Manager wants to own -> the same name with a .backup suffix
    - /home/lz/.zsh_history (file) -> .zsh_history.pre-dotfiles.bak, then linked to …

? Proceed with this plan? [Y/n]
```

最后一节是刻意单列的：挪动你已有的文件是 bootstrap 唯一会碰到你数据的地方，
因此逐个文件列出、放在最后、就在你作答的位置旁边。

回答 yes 之外的任何内容都会直接退出，不改动任何东西。全程只有这**一个**提问——
不会一步一步反复打扰。**没有终端**的运行（CI、容器构建、cron、`bash -c`）不会提问，
行为与以往完全一致；在终端上加 `--yes` 也可以跳过提问（计划仍会打印）。设计记录见
[ADR-0010](docs/plans/adr-0010-plan-first-one-shot-clearance-2026-08-04.md)。

## bootstrap 做了什么

以 Home Manager 切换为界一分为二：

1. **HM 之前（shell）：** 检测权限（root / sudo / 无）→ 安装前置依赖 →
   **安装 Lix** → 配置 Nix（+ 可选的 CERNET 镜像）→
   **构建并激活 Home Manager**（使用 `-b backup`）。
2. **HM 之后（通过 `uv` 运行 Python）：** 应用 JSON(C) 链接映射（若设置了
   `DOTFILE_LINK_MAP_JSON`）→ 把登录 shell 设为 Nix 的 zsh（`chsh`）→
   写入延迟执行的 Claude 配置 → 安装任意可选的 Linux 系统组件。

执行完成后，启动它的那个 shell 仍保留**旧的** PATH，因此直接输入 `zsh` 还找不到。
用它打印出来的绝对路径启动新环境，或者直接重新登录（你的登录 shell 已经是 zsh）：

```bash
exec ~/.nix-profile/bin/zsh -l
```

## 参数与环境变量

| 参数              | 效果                                               |
| ----------------- | -------------------------------------------------- |
| `--dry-run`       | 打印每条命令但不执行（不会征求许可——没有要许可的东西）。 |
| `--verbose`       | 执行时回显每条命令。                               |
| `--yes` / `-y`    | 跳过许可提问（计划仍会打印）。等同于 `DF_ASSUME_YES=1`。 |
| `--network CN`    | 为 Nix、pypi/uv 和 rustup 启用中国（CERNET）镜像。 |
| `--system <list>` | 安装可选的 Linux 系统组件（`all` = 全部）。        |
| `--host NAME`     | 强制使用指定的 flake host，而非自动检测。          |
| `--no-claude`     | 跳过写入 Claude/Lark/MCP 的后置配置。              |

| 环境变量                    | 效果                                                                                                                                                                                                                                                                                                                            |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DF_ASSUME_YES=1`           | 跳过交互许可（等同于 `--yes`）；你许可计划之后它会被自动导出，因此后续步骤不会重复提问。                                                                                                                                                                                                                                         |
| `DOTFILE_NETWORK_ENV=CN`    | 等同于 `--network CN`（zsh 环境也会读取它用于 pypi/rustup）。                                                                                                                                                                                                                                                                   |
| `DOTFILE_SYSTEM_COMPONENTS` | `--system` 的回退值（如 `all`）；参数优先。                                                                                                                                                                                                                                                                                     |
| `DOTFILE_FLAKE_CACHE`       | 含 `seed-paths.txt` 的目录，用于给 flake 输入做种（CN/离线/CI）。                                                                                                                                                                                                                                                               |
| `DOTFILE_LINK_MAP_JSON`     | 可选：指向一个 JSON/JSONC 链接映射文件（`{"links":{"<标签>":{"source","target","type":"dir"\|"file"}}}`），作为 post-HM **第一步**执行。未设置则跳过；设置了但文件不存在则报错。目标若已是真实文件/目录，先备份为 `.pre-dotfiles.bak` 再链接；源的类型/存在性不匹配会告警（并在结束时汇总）。示例见 `platform/link-map.jsonc`。 |

## 在新机器上试用（以及如何恢复）

**安全模型——不会破坏任何东西：**

- **先预览：** `./bootstrap.sh --dry-run --verbose` 什么都不执行。普通的交互式运行
  也会先打印完整计划并等待你的许可，之后才做第一处改动。
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

## 组件分类

组件分为两大类：

- **用户组件** —— 声明式，由 Home Manager 在 `home/packages.nix` 中管理。
- **系统组件** —— 命令式，由 `platform/setup.py` 通过
  `platform/installers/components.py` 的 `OptionalComponent` 注册表安装。

### 用户组件

用户组件是 Home Manager 每次切换时安装的包。它们构成默认的用户环境，
包括核心 CLI 工具集、运行时支持，以及你直接使用的工具。

- **默认用户组件** 是 `home/packages.nix` 中适用于所有主机的主列表。
  例如 `ripgrep`、`jq`、`fd`、`tree`、`wget`、`uv` 等核心工具。
- **条件用户组件** 仍然是声明式的，但受 OS 或构建时条件控制，例如 Linux
  上的 `xclip`。

这些用户组件不是由 `--system` 选择；它们由 Home Manager 在 bootstrap
过程中始终应用。

### 系统组件

系统组件是 Home Manager 在非 NixOS 主机上无法拥有的内容。它们通过
`--system <list>` 或 `DOTFILE_SYSTEM_COMPONENTS` 选择，
在 Home Manager 切换之后安装。

- **必要的系统组件**
  - Debian/Ubuntu 上的 `software-properties`。它提供 `add-apt-repository`，
    是 docker/nvidia/llvm 仓库配置的前置条件。只要 `run_system` 运行，
    就会安装它；只有 `--system none` 会跳过。
- **可选的系统组件**
  - `docker` — Docker Engine（rootful）
  - `docker-rootless` — Docker（rootless）
  - `cuda` — CUDA Toolkit 12.6
  - `nvidia` — NVIDIA 驱动 + container toolkit
  - `llvm` — LLVM 18（+ `update-alternatives`）
  - `brew` — 仅 macOS 上的 Homebrew 本体（不含 formulae/casks）

`--system` 支持逗号分隔的组件名、别名组和 `all`；如果同时选择了
`docker` 和 `docker-rootless`，则保留 rootless。未指定时会使用默认组：
macOS 为 `brew`，Linux 则没有额外的可选系统组件，但如果适用的话仍会
安装 `software-properties`，除非指定 `--system none`。

```bash
./bootstrap.sh                       # 用户组件 + 默认系统组件
./bootstrap.sh --system docker,llvm  # 系统组件 + 必要的 Linux 前置条件
./bootstrap.sh --system all          # 安装适用于本 OS 的所有系统组件
./bootstrap.sh --system none         # 完全不装系统组件（连必要组件也跳过）
DOTFILE_SYSTEM_COMPONENTS=cuda,nvidia ./bootstrap.sh
```

要在 bootstrap 之后添加组件，有一个手动交互式选择器：

```bash
./nix-system-interactive-install.sh            # 选择 + 安装
./nix-system-interactive-install.sh --dry-run  # 仅预览
```

| 名称                  | 描述                                                                | OS             |
| --------------------- | ------------------------------------------------------------------- | -------------- |
| `software-properties` | `add-apt-repository` 支持 **（Linux 必需 —— 始终安装）**            | debian, ubuntu |
| `docker`              | Docker Engine（rootful）                                            | debian, ubuntu |
| `docker-rootless`     | Docker（rootless）                                                  | debian, ubuntu |
| `cuda`                | CUDA Toolkit 12.6                                                   | debian, ubuntu |
| `nvidia`              | NVIDIA 驱动 + container toolkit                                     | debian, ubuntu |
| `llvm`                | LLVM 18（+ `update-alternatives`）                                  | debian, ubuntu |
| `brew`                | Homebrew —— 仅包管理器本身（不含 formulae/casks）**（macOS 默认）** | darwin         |

在 macOS 上，bootstrap **默认不**安装 Homebrew（CLI 工具来自 nixpkgs）。
用 `--system brew`（或 `--system all`）添加它；在 CN 环境会使用 BFSU 镜像。
它只安装 Homebrew _本身_——GUI 应用请自行用 `brew install --cask <app>` 添加。

对于 GUI 应用，有一个手动的**交互式 cask 选择器**（不会自动运行）：

```bash
./brew-cask-interactive-install.sh
```

它运行一个小的 `uv` 脚本（[platform/brew_cask_install.py](platform/brew_cask_install.py)，
依赖以 uv script 模式内联声明），将推荐的 cask 以清单形式展示（Edge + Alacritty
预先勾选——在文件里编辑列表），允许你为本次运行选择一个 Homebrew 镜像
（默认跟随 `DOTFILE_NETWORK_ENV`），然后安装你的选择。

随时列出它们：`uv run platform/installers/components.py`。

## 添加软件包（教程）

一个新工具该写在哪里，取决于它归哪一层管：

| 你想要的                                          | 写进哪里                                                        | 作用范围                                       |
| ------------------------------------------------- | --------------------------------------------------------------- | ---------------------------------------------- |
| nixpkgs 里已有的 CLI 工具                         | `home/packages.nix`                                             | 所有主机，每次 switch 都应用                   |
| 运行时，或只在 npm/cargo/go/gh-release 发布的工具 | `home/mise.nix`（`programs.mise.globalConfig.tools`）           | 所有主机，`mise install` 之后生效              |
| 只有某一个项目需要的东西                          | 该项目自己的 `mise.toml`，**或**该项目自己的 `flake.nix` devShell | 该目录树                                       |
| 守护进程/驱动/apt 层面的东西（docker、cuda、llvm…）| `platform/installers/components.py` + `--system`                | 见 [组件分类](#组件分类)                       |
| 只想试一下                                        | 什么都不写 —— `nix shell nixpkgs#<pkg>`                          | 仅当前 shell                                   |

**用户级的东西一律不用命令式安装。** Home Manager 会把它的 `home-manager-path`
安装进 `~/.nix-profile` 指向的那个 profile，所以在旁边额外 `nix profile install` /
`nix-env -i` 会和它争抢同名文件，也不会同步到另一台机器，还不会出现在
`home-manager packages` 里。想让工具明天还在，就把它写进本仓库的某个文件。

### Nix —— 查找软件包

```bash
nix search nixpkgs hyperfine     # 按正则匹配 nixpkgs 的 attribute + 描述
nix search nixpkgs '^ripgrep$'   # 加锚点：精确的 attribute 名
```

或用 [search.nixos.org/packages](https://search.nixos.org/packages)——同样的数据，
还会列出 attribute 名和包提供的可执行文件。

`nix search nixpkgs` 解析的是 *registry* 里的 nixpkgs（当前 unstable），而本仓库
是按 `flake.lock` 锁定的 revision 构建的。确认该 attribute 在锁定版本里存在、
并看看你实际会拿到哪个版本：

```bash
nix eval --raw .#homeConfigurations.dotfiles-debian.pkgs.ripgrep.version   # -> 15.1.0
```

在决定长期保留之前先试用——它只把工具放进当前 shell 的 `PATH`，不做任何持久化：

```bash
nix shell nixpkgs#hyperfine      # 然后：hyperfine --version
```

### Nix —— 全局（持久化到 `home/packages.nix`）

把 attribute 加进 [`home/packages.nix`](home/packages.nix) 的列表里，放在它所属的
分组中；如果只在某个 OS 上需要，用 `lib.optionals stdenv.isLinux` /
`isDarwin` 包起来（`home/packages.nix:47`）：

```nix
      ripgrep
      jq
+     hyperfine # benchmarking
```

unfree 包不需要额外步骤——`mkHome` 实例化 nixpkgs 时已设置
`config.allowUnfree = true`（`flake.nix:41`）。然后
[同步到你的 home](#把改动同步到当前的-home)。

### Nix —— 项目内

项目依赖绝不要写进 `home/packages.nix`。临时用（在项目目录里）：

```bash
nix shell nixpkgs#ffmpeg nixpkgs#imagemagick   # 仅当前 shell，不持久化
```

要可复现，就给*那个*项目自己的 flake 加一个 devShell，用 `nix develop` 进入
（把它的 `flake.nix` + `flake.lock` 提交到该项目）：

```nix
# <project>/flake.nix
{
  inputs.nixpkgs.url = "github:nixos/nixpkgs/nixpkgs-unstable";
  outputs =
    { nixpkgs, ... }:
    let
      pkgs = nixpkgs.legacyPackages.x86_64-linux;
    in
    {
      devShells.x86_64-linux.default = pkgs.mkShell {
        packages = [ pkgs.ffmpeg pkgs.imagemagick ];
      };
    };
}
```

想让它在 `cd` 时自动加载，就往*本*配置里加 direnv
（在某个 `home/*.nix` 模块中写 `programs.direnv.enable = true;` +
`nix-direnv.enable = true;`——目前配置里还没有），并在项目里放一行
`.envrc`（`use flake`）。

### mise —— 查找工具

```bash
mise registry | grep -i terraform   # 工具名 -> mise 会使用的 backend
mise ls-remote node                 # 某个工具可用的版本
```

短名字通过 mise 的 registry 解析（core/aqua/ubi）；其他 backend 要显式写出：
`npm:<pkg>`、`cargo:<crate>`、`go:<module>`、`pipx:<pkg>`、`ubi:<owner>/<repo>`。

### mise —— 全局（持久化到 `home/mise.nix`）

`~/.config/mise/config.toml` 是**生成的**：Home Manager 把它软链接到 nix store，
因此 `mise use --global …` 无法在那里持久化（写入会碰到只读的 store 路径；
以 root 运行则会改到 store 里的副本，下一次 switch 就被还原）。全局工具列表在
[`home/mise.nix`](home/mise.nix)：

```nix
        just = "latest";
        node = "lts";
+       terraform = "latest";
+       "npm:@openai/codex" = "latest";
```

npm 系的工具用 **pnpm** 安装（`npm.package_manager = "pnpm"`，
`home/mise.nix:21`），而 pnpm 默认阻止依赖的生命周期脚本。如果某个包确实需要它的
`postinstall`，就像 `@smithery/cli` 那样精确放行这一个包（`home/mise.nix:38`）：

```nix
        "npm:@smithery/cli" = {
          version = "latest";
          allow_builds = [ "@smithery/cli" ];
        };
```

然后切换并实体化——只是声明、尚未安装的工具不会进 `PATH`，要跑过
`mise install` 才行（`home/mise.nix:3-8`）：

```bash
home-manager switch --flake .#dotfiles-debian -b backup
mise install                     # 安装全局配置声明的全部工具
mise ls                          # 查看已安装 / 生效的版本
```

**只针对单台机器的逃生口：** mise 也会读 `~/.config/mise/conf.d/*.toml`，
这个目录不由 Home Manager 拥有——放在那里的文件能在 switch 后存活，
适合放本机专属的工具。代价一如往常：它在 git 之外，别的机器不会有。

### mise —— 项目内

```bash
cd <project>
mise use node@22 python@3.12   # 写入（必要时创建）./mise.toml 并安装
mise trust                     # 从 git 拿到的、不是你自己写的 mise.toml 需要先信任
mise current                   # 当前目录生效的版本
mise which node                # 实际解析到哪个 shim/二进制
```

把 `mise.toml` 提交到那个项目里；项目配置与 Home Manager 互不相干。
`mise up` 在声明的范围内升级（也适用于全局配置，因为它不改写配置文件）；
`mise up --bump` *会*改写配置文件，所以全局工具的版本变更请改
`home/mise.nix`。

### 修改 Home Manager 配置

| 想改什么                                | 文件                                                                 |
| --------------------------------------- | -------------------------------------------------------------------- |
| zsh 选项/插件、`PATH`、session 变量     | `home/shell.nix`                                                     |
| zsh 函数、别名、fzf-tab 细节            | `home/zsh/functions.zsh`、`home/zsh/fzf-tab.zsh`（原样 source）      |
| 提示符                                  | `home/starship.toml`（由 `home/starship.nix` 读取）                   |
| git 配置                                | `home/git.nix`；别名在 `home/git-aliases.conf`                        |
| tmux                                    | `home/tmux.conf`（+ `home/tmux.nix`）                                 |
| 指向环境专属可变路径的链接              | `home/env-links.nix`（ADR-0009 Tier B —— 真实条目只在 env 分支上）    |
| 新机器                                  | `flake.nix:17` 的 `hosts` attrset                                     |

有两个约定值得保持（见 [AGENT.md](AGENT.md)）：优先使用上游的 `programs.*` 选项
而不是自己拼配置；大段内容用原样嵌入文件（`builtins.readFile` /
`source ${./file}`），不要转义进 nix 字符串。不要调整 `home/shell.nix` 里 zsh
插件的顺序——completions → fzf-tab → autosuggestions → 语法高亮放最后，
这个顺序关乎正确性。

### 把改动同步到当前的 home

上面所有改动在 Home Manager 切换之前都不生效。在仓库目录里：

```bash
# 1) 预览：构建新 generation，不激活，也不留下 ./result 软链接
nix build --no-link --print-out-paths .#homeConfigurations.dotfiles-debian.activationPackage
nix store diff-closures /nix/var/nix/profiles/per-user/"$USER"/home-manager <上面打印的路径>

# 2) 激活
home-manager switch --flake .#dotfiles-debian -b backup
```

**用哪个 host？** 如果 `flake.nix` 里定义了你的 hostname 就用它，否则用 OS/架构
的默认值（`platform/lib.sh:211`）。其他用户——包括 root——走非纯（impure）的
`generic` 回退 host，需要加 `--impure`：

```bash
home-manager switch --flake .#generic -b backup --impure
```

`-b backup` 与 bootstrap 的做法一致（`HOME_MANAGER_BACKUP_EXT=backup`）；
不加它的话，一旦发现该放软链接的位置上是真实文件，switch 就会中止。
也可以直接让 bootstrap 来做——它会检测 host，并把 post-HM 的步骤也重跑一遍：

```bash
./bootstrap.sh --dry-run --verbose   # 预览全过程
./bootstrap.sh --yes                 # 直接执行，跳过许可提问
```

之后在你的 shell 里：

```bash
exec zsh -l                          # 加载新的 PATH / 环境变量 / 补全
mise install                         # 实体化新声明的 mise 工具
home-manager packages | grep hyperfine   # 确认这个 generation 里确实有它
```

如果结果不对：`home-manager switch --rollback`——见
[在新机器上试用（以及如何恢复）](#在新机器上试用以及如何恢复)。

**升级版本**（区别于添加软件包）：

```bash
nix flake update                     # 全部 input
nix flake update nixpkgs             # 只更新 nixpkgs
home-manager switch --flake .#dotfiles-debian -b backup
mise up                              # mise 工具，在声明的范围内升级
```

把改动后的 `flake.lock` 与需要它的那次改动一起提交。

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
