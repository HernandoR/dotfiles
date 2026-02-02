# Bash Shell 登陆卡住问题修复文档

## 问题描述

在执行 `bootstrap.sh` 之后，默认登陆的 bash shell 会卡住，需要按 Ctrl-C 才能进入。zsh shell 登陆正常。

## 根本原因

通过分析配置文件，发现存在循环引用（circular reference）问题：

1. **登陆 shell** 启动时会加载 `.bash_profile`
2. `.bash_profile` 第 51 行：`. ~/.bashrc` 会加载 `.bashrc`
3. `.bashrc` 第 1 行：`[ -n "$PS1" ] && source ~/.bash_profile;` 又会加载 `.bash_profile`

这样就形成了无限循环：`.bash_profile` → `.bashrc` → `.bash_profile` → `.bashrc` → ...

## Bash Shell 初始化流程说明

### 正确的初始化流程

**登陆 Shell（Login Shell）：**
- 读取顺序：`/etc/profile` → `~/.bash_profile` → `~/.bash_login` → `~/.profile`
- `.bash_profile` 应该负责设置环境变量和加载 `.bashrc`

**非登陆 Shell（Non-login Shell）：**
- 只读取 `~/.bashrc`
- `.bashrc` 应该负责设置交互式 shell 的配置（别名、函数等）

### 配置文件职责

- **`.bash_profile`**: 
  - 用于登陆 shell
  - 设置环境变量（PATH、EDITOR 等）
  - 应该在末尾 source `.bashrc` 以确保交互式配置也生效
  
- **`.bashrc`**:
  - 用于非登陆 shell（每次打开新终端窗口）
  - 设置别名、函数、命令提示符等交互式配置
  - **不应该** source `.bash_profile` 以避免循环引用

- **`.profile`**:
  - POSIX 兼容的配置文件
  - 如果 `.bash_profile` 不存在时会被读取
  - 通常会 source `.bashrc`（如果是 bash shell）

## 修复方案

### 修改内容

**文件：** `sources/root/.bashrc`

**修改前（第 1 行）：**
```bash
[ -n "$PS1" ] && source ~/.bash_profile;
```

**修改后：**
```bash
# .bashrc should NOT source .bash_profile to avoid circular references
# .bash_profile already sources .bashrc for login shells
```

### 修改说明

1. 移除了 `.bashrc` 中对 `.bash_profile` 的引用
2. 添加了注释说明原因，防止未来再次引入相同问题
3. 保持 `.bash_profile` 中对 `.bashrc` 的引用（第 51 行），这是正确的做法

## 验证测试

使用以下命令测试修复后的配置：

```bash
# 测试登陆 shell 是否能正常启动（5秒超时）
timeout 5 bash --login -c "echo 'Bash login successful'"
```

**预期结果：**
- bash 能够在 5 秒内成功启动并输出 "Bash login successful"
- 不会出现卡死或需要 Ctrl-C 中断的情况

## 其他注意事项

1. 如果用户已经运行过 `bootstrap.sh`，需要重新运行以应用修复：
   ```bash
   ./restore_and_backup.sh restore
   ```

2. 这个修复不影响 zsh 的使用，zsh 有自己独立的配置文件（`.zshrc`、`.zshenv` 等）

3. 如果用户自定义了额外的配置，建议将环境变量设置放在 `.bash_profile` 或 `.profile` 中，将交互式配置放在 `.bashrc` 中

## 参考资料

- [Bash Startup Files](https://www.gnu.org/software/bash/manual/html_node/Bash-Startup-Files.html)
- [Difference between .bashrc and .bash_profile](https://stackoverflow.com/questions/415403/whats-the-difference-between-bashrc-bash-profile-and-environment)
