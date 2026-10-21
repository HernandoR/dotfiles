# ~/.config/zsh/claude-env.zsh — Claude Code's CLAUDE_ENV_FILE (managed by
# chezmoi; seeded into ~/.claude/settings.json by scripts/agents.py).
#
# Claude inlines this file into every Bash-tool command, AFTER it replays its
# shell snapshot. That snapshot ends in `export PATH=<the Claude process's own
# PATH>`, which overwrites what .zshenv -> env.zsh just built — so a Claude
# launched from a bare environment (the desktop app's remote server) loses the
# mise shims, ~/.local/bin and the default Node. Running env.zsh again here puts
# them back in front; the snapshot's entries, plugin bins included, stay behind.
[ -n "$ZSH_VERSION" ] && [ -r "$HOME/.config/zsh/env.zsh" ] && . "$HOME/.config/zsh/env.zsh"
