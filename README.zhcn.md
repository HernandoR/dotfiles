# lz 的 dotfiles

跨平台 dotfiles：**[chezmoi](https://www.chezmoi.io/)** 管文件，
**[mise](https://mise.jdx.dev/)** 管运行时和绝大部分 CLI 工具（预编译发布二进制），
**[nvm](https://github.com/nvm-sh/nvm)** 管 Node 生态，**[zoi](https://github.com/Zillowe/Zoi)**
作为其自有仓库软件包的入口，其余命令式步骤（包括少数系统级软件包）由若干
**`uv run` Python 脚本**完成。目标平台：macOS (aarch64) 与 Debian/Ubuntu (x86_64 + aarch64)。
zsh + Starship (catppuccin_mocha) + fzf-tab 的体验不变。

完整手册见英文 [README.md](README.md)；设计记录见
[ADR-0013](docs/plans/adr-0013-chezmoi-zoi-mise-uv-2026-09-09.md) 与
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

只需要 `curl` 和 `git`。用户层（uv、zoi、chezmoi、mise，全部装进 `~/.local/bin`）
不需要 root；root/sudo 只用于缺失的前置依赖、`chsh` 以及可选的系统组件。

在终端里运行时，它会先打印完整计划——安装什么、写入/链接哪些文件、会复制备份哪些
现有文件——然后**只询问一次**（ADR-0010）。无终端（CI、容器构建）时不会询问；
`--yes` 也可跳过。

## bootstrap 做了什么

1. **工具：** 检测权限 → 安装前置依赖 → 用各自的安装脚本安装 zoi、chezmoi、mise
   （先下载再执行，绝不 `curl | sh`）。
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
| `just diff` / `just apply` / `just status` | 查看差异 / 应用 / 逐文件状态 |
| `just check` | 校验仓库：数据文件、脚本、每个环境的完整渲染 |
| `just update` | `git pull` + apply + `zoi update --all` + `mise up` |

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
  zoi 仅用于其自有仓库里的包（实测 2026-09-09 其仓库只有九个包、原生透传不装东西）。

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
