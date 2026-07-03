# 概念说明 · context.md

本文档解释本 dotfiles 仓库里反复出现的核心概念，方便快速上手与协作。
实现细节以代码为准，文中标注了 `文件:行号` 便于溯源；架构决策见 `docs/plans/` 下的 ADR。

---

## 一、目录（Directories）

整个安装的核心是把「仓库里的配置」搬进「你的家目录」，中间经过一个暂存目录中转。
三个目录构成一条单向流水线：

```
sources/root/              ~/dotfiles                 $HOME
  (source 源目录)   ──rsync──►  (stage 暂存目录)  ──symlink──►  (target home 目标家目录)
  仓库里的真实配置    排除 .ex_list   中转/落盘一份           软链接指回暂存目录
```

### 1. `source` 目录（源目录）

- **位置**：仓库内的 `sources/root/`。
- **含义**：真正要部署的 dotfiles「唯一权威来源」（single source of truth）——
  例如 `.zshrc`、`.exports`、`.path`、`.config/…` 等，都按相对 `$HOME` 的路径存放。
  改这里 = 改你最终生效的 shell 配置。
- **`sources/` 下的其它内容**：
  - `sources/.ex_list`：rsync 的 `--exclude-from` 排除清单（cache/lock/swap 噪声）。
  - `sources/zsh_plugins/`：拷贝进 `~/.oh-my-zsh/custom/plugins` 的 zsh 插件配置。
  - `sources/install/`：独立的辅助安装脚本（应用类）。
  - `sources/unusing/`：已退役、暂不启用的配置。

### 2. `stage` 目录（暂存目录）

- **位置**：默认 `~/dotfiles`（即 `$HOME/dotfiles`）；
  若设置了环境变量 `DOTFILE_EDIT_HOME_TARGET`，则为 `$DOTFILE_EDIT_HOME_TARGET/dotfiles`。
  由 `_dotfiles_staging_dir()` 决定（`main.py:24`）。
- **含义**：`sources/root/` 经 `rsync`（排除 `.ex_list`）复制到此处，作为落盘的一份「中转副本」。
  真正链接到家目录的软链接，其目标指向的是**暂存目录里的文件**，而非仓库。
  这样即便仓库移动/删除，已链接的家目录仍指向一份稳定副本。
- **相关函数**：`stage_dotfiles()`（`main.py:179`）。

### 3. `target home` 目录（目标家目录）

- **位置**：`$HOME`（`Path.home()`），也就是当前用户的家目录。
- **含义**：最终落地处。`link_dotfiles()`（`main.py:222`）遍历暂存目录，把每个条目
  **软链接**回 `$HOME`；已存在的真实文件会先备份（`*.pre-dotfiles.bak`）再让路，
  已正确链接的会跳过（幂等）。
- **例外**（不走通用软链接流程）：
  - `.claude`、`.claude.json`：由 Claude 后置安装重建（ADR-0005）。
  - `.ssh` 密钥：是**拷贝**而非软链接（ADR-0006），保证严格权限的真实文件。

---

## 二、组件（Components）

「组件」是安装系统的最小单元，代表「装某样东西」这件事。
所有组件共享 `Component` 基类的安装机制，只在**生命周期**上分两类（ADR-0003 / ADR-0004）。

### 1. `component`（组件基类）

- **位置**：`Component`（`components.py:34`）。
- **声明式优先**：只需列出 `installs = {manager_id: spec}`，基类的 `install()`
  会把它交给编排器挑中的后端去执行（`components.py:73`）。spec 可以是：
  - 纯字符串 = 包名（`apt` / `brew`）；
  - `Deb(url)` = 下载一个 `.deb` 再 `apt install -f`；
  - `Script(url, interpreter, args)` = 用 `scripts` 后端下载并执行脚本。
- **命令式逃生口**：多步安装可重写 `install(self, ctx)`，并复用后端
  （如 `ctx.package_manager("scripts").install(ctx, Script(...))`）。

### 2. `necessary component`（必要组件）

- **位置**：`NecessaryComponent`（`components.py:92`）。
- **含义**：每次运行都装的基础 shell 工具，**不可由用户选择**。
  安装顺序对正确性至关重要，因此目录不是靠注册顺序，而是文件底部一条显式元组：
  `NECESSARY = (OhMyZsh, Fzf, Starship, Node)`（`components.py:786`），由
  `run_necessary_components()`（`main.py:326`）按序执行。
- **约束（ADR-0004）**：只装二进制/框架，**绝不写 shell rc 文件**——
  仓库的 `.zshrc` 才是权威（`KEEP_ZSHRC=yes`、fzf `--no-update-rc`、
  nvm `PROFILE=/dev/null`）。`Node` 之所以是必要组件，是因为 Claude 后置安装与
  多个可选组件都依赖它。

### 3. `optional component`（可选组件）

- **位置**：`OptionalComponent`（`components.py:108`）。
- **含义**：用户按需选装的组件。定义子类并设置小写 `name` 即通过
  `__init_subclass__`（`components.py:120`）**自动注册**。
- **选择方式**：
  - 命令行：`--optional-components docker,claude`
  - 环境变量：`DOTFILE_BOOTSTRAP_OPTIONAL_COMPONENTS=all`（命令行优先）
  - `resolve()`（`components.py:142`）支持别名组，如 `all`（安装所有归入 `all` 组的组件）。
- **示例**：`docker`、`claude`、`rustup`、`codegraph`，以及本次新增的：
  - `gh`：GitHub CLI（macOS 走 brew 公式；Debian 走固定版本 `.deb`）。
  - `jj`：Jujutsu，Git 兼容的版本控制系统（macOS 走 brew；Linux 下载 musl 预编译包，
    把 `jj` 二进制放进 `~/.local/bin`，该路径已在 `sources/root/.path` 中加入 PATH）。

---

## 三、工具与管理（Tools & Management）

### 1. `installers`（安装器包）

- **位置**：`installers/` 目录，即「怎么装」的全部逻辑：
  - `installers/components.py`：组件目录（必要组件 + 可选组件注册表）。
  - `installers/managers.py`：安装后端（`PackageManager`）与 spec 类型（`Deb` / `Script`）。
  - `installers/__init__.py`：空文件，标记为 Python 包。
- **要点**：这里**没有** `debian.py` / `macos.py` 之类的分 OS 模块（ADR-0003 已删除）；
  每个组件自己的安装逻辑都写在 `components.py` 的组件类上。

### 2. `manager`（管理器 / 后端）

「manager」在本仓库有两个层面，注意区分：

- **(a) `PackageManager` 安装后端**（`managers.py:54`）
  真正「执行安装」的后端，按 `id` 自注册：
  - `apt`（`managers.py:86`，仅 debian/ubuntu，priority 100）
  - `brew`（`managers.py:106`，仅 darwin，priority 100）
  - `scripts`（`managers.py:115`，全平台，priority 10，远程 bootstrap 脚本兜底）

  每个后端声明 `supported_os` 与 `priority`；**由编排器按优先级挑后端**
  （原生包管理器优先于脚本），组件自己从不选后端。

- **(b) `DotfilesManager` 总编排器**（`main.py`）
  整个流程的编排者，同时也是传给每个组件的**上下文对象 `ctx`**。组件通过它调用：
  - `ctx.run_command(...)`：统一的命令执行入口（root 下自动去掉 `sudo`、支持 `--dry-run`、
    失败即退出，`main.py:70`）。
  - `ctx.package_manager(id)`（`main.py:301`）：取某个后端实例。
  - `ctx.select_manager(installs)`：按优先级为一组 `installs` 选出适用后端。
  - `ctx.os_type`：`"darwin"` / `"debian"` / `"ubuntu"`。

---

## 四、其它信息（Other info）

### 安装的四个阶段（`run()`，`main.py:447`）

1. **OS 预备**：`bootstrap_macos()` / `bootstrap_debian()`——装 git、zsh、rsync 等核心包
   （不属于组件系统，ADR-0003 §7）。
2. **必要组件**：`run_necessary_components()`——按 `NECESSARY` 顺序安装。
3. **迁移 dotfiles**：`migrate_dotfiles()`——先 `stage_dotfiles`（rsync 到暂存目录），
   再 `link_dotfiles`（软链接进 `$HOME`），最后 `deploy_ssh_keys`（拷贝 SSH 密钥）。
   放在工具之后，保证仓库的 rc 文件最终胜出（ADR-0004 §4）。
4. **设置默认 shell**：`set_default_shell()`——幂等地把登录 shell 切成 zsh。
5. **可选组件**：`run_optional_installers()`——安装用户选中的组件。

### 常用命令

```bash
./bootstrap.sh                              # 完整引导（装 uv，跑 main.py）
./bootstrap.sh --dry-run --verbose          # 只打印命令、不执行（参数透传给 main.py）
uv run main.py --interactive                # 允许交互式提示（OMZ、Starship）
uv run main.py --optional-components gh,jj  # 只装指定可选组件
DOTFILE_BOOTSTRAP_OPTIONAL_COMPONENTS=all uv run main.py

uv run -m installers.components             # 列出所有可选组件及其后端/OS/分组
```

> 无 Makefile / test 框架：验证改动用 `uv run main.py --dry-run --verbose`（打印每条命令而不执行）。

### 架构决策记录（ADR，`docs/plans/`）

- ADR-0001：暂存与软链接策略（source → stage → target home）
- ADR-0003：`PackageManager` 安装抽象
- ADR-0004：必要组件 + 阶段分离（rc 文件归属）
- ADR-0005：Claude 后置安装（重建 `~/.claude`）
- ADR-0006：SSH 密钥以拷贝方式部署

### fzf-tab 配置

fzf-tab 的插件加载与配置写在 `sources/root/.zshrc`：它必须在 `zsh-completions`
**之后**、`zsh-autosuggestions` / `zsh-syntax-highlighting` **之前**加载，否则补全菜单
无法被 fzf 接管。相关的 `zstyle` 设置（分组表头、`LS_COLORS` 着色、`cd` 目录预览、
tmux 弹窗等）紧跟在 `antigen apply` 之后。
