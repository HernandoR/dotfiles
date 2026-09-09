# lz 的 dotfiles

跨平台 dotfiles：**[chezmoi](https://www.chezmoi.io/)** 管文件，
**[zoi](https://github.com/Zillowe/Zoi)** 作为软件包安装的统一入口，
**[mise](https://mise.jdx.dev/)** 管运行时，其余命令式步骤由若干 **`uv run` Python
脚本**完成。目标平台：macOS (aarch64) 与 Debian/Ubuntu (x86_64 + aarch64)。
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
   zsh 插件，最后按需运行 packages（zoi）、字体、`mise install`、
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
- **先播种后交出**（mise 的全局工具列表）：`mise.toml` 只是
  `~/.config/mise/config.toml` 的种子，之后归 mise 所有（`mise use -g`）。
- **软件包**（`packages.toml`）：`packages.py` 先交给 `zoi install`，再逐个校验
  可执行文件，缺失则回退到原生包管理器，再回退到 `mise use -g`。实测
  （2026-09-09）zoi 的仓库只有九个包、原生透传没有真正安装东西，因此当前实际生效的
  是回退路径；zoi 一旦可用，脚本无需改动。

### 机器本地的“逃生口”

`~/.path`、`~/.exports`（每个 zsh 都会读取，`.zshenv` 与 `.zprofile` 各读一次，
所以能覆盖仓库设置并把 PATH 放到最前）、`~/.proxy`、`~/.extra`（交互式 zsh 最后
读取）。它们位于 stateRoot 上、被软链进 `$HOME`，仓库只负责创建，从不改写。

## 添加软件

- CLI 工具 → `home/.chezmoidata/packages.toml`（每个包管理器一个名字，没有的写 `""`，
  可加 `mise = "..."` 作回退）。
- 运行时 → `home/.chezmoidata/mise.toml`（已 bootstrap 的机器用
  `mise use -g <tool>@<version>` 追加）。
- 需要持久化的 `$HOME` 路径 → `home/.chezmoidata/envlinks.toml`。
- 普通 dotfile → `home/`（`chezmoi add ~/.config/tool/config`）。
- 系统组件 / agent 能力 → `scripts/components.py` / `scripts/agents.py`。

## 验证

没有测试框架。`just check` 运行 `scripts/check.py`：校验三个数据文件、编译并
`--help` 每个脚本、按环境把整棵树渲染进临时 `$HOME` 并用 `zsh -n`、
`git config --list`、TOML 解析检查结果。`./bootstrap.sh --dry-run --verbose`
展示完整计划与 chezmoi 的 diff。
