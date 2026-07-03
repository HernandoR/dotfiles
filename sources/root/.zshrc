# Zsh interactive shell configuration.
# .zshenv has already sourced .tools, .exports, .path, and interactive dotfiles.
# This file handles zsh-specific plugin/theme initialization.

source $HOME/antigen.zsh

antigen use oh-my-zsh

antigen bundle z

antigen bundle brew
antigen bundle command-not-found
# antigen bundle docker
# antigen bundle docker-compose
antigen bundle gem
antigen bundle git
antigen bundle golang
antigen bundle heroku
antigen bundle lein
antigen bundle ng
antigen bundle osx
antigen bundle pip

# Load order matters: completions register first, then fzf-tab binds the
# completion widget, and only afterwards do autosuggestions / syntax-highlighting
# wrap widgets. fzf-tab must sit between them or its menu won't take over.
antigen bundle zsh-users/zsh-completions
antigen bundle Aloxaf/fzf-tab
antigen bundle zsh-users/zsh-autosuggestions
antigen bundle zsh-users/zsh-syntax-highlighting
antigen bundle zsh-users/zsh-apple-touchbar

antigen apply

# fzf key bindings and fuzzy completion
[ -f ~/.fzf.zsh ] && source ~/.fzf.zsh

# ── fzf-tab (Aloxaf/fzf-tab) ────────────────────────────────────────────────
# Replaces zsh's default completion menu with an fzf picker. These zstyles are
# read at completion time, so they apply after the bundle above is loaded.

# compsys integration
zstyle ':completion:*:descriptions' format '[%d]'         # group headers (needed for group colors)
zstyle ':completion:*' list-colors ${(s.:.)LS_COLORS}     # colorize entries by file type
zstyle ':completion:*' menu no                            # disable zsh's menu so fzf-tab takes over
zstyle ':completion:*:git-checkout:*' sort false          # keep git refs in their natural order

# fzf-tab behavior
zstyle ':fzf-tab:*' use-fzf-default-opts yes              # honor $FZF_DEFAULT_OPTS
zstyle ':fzf-tab:*' switch-group '<' '>'                  # cycle completion groups with < / >
zstyle ':fzf-tab:*' fzf-min-height 15

# preview directory contents when completing `cd` (eza if present, else ls)
zstyle ':fzf-tab:complete:cd:*' fzf-preview \
  'if command -v eza >/dev/null 2>&1; then eza -1 --color=always --icons=auto "$realpath"; else ls -1 "$realpath"; fi'

# use a tmux popup for the picker inside tmux (falls back to inline fzf otherwise)
zstyle ':fzf-tab:*' fzf-command ftb-tmux-popup
zstyle ':fzf-tab:*' popup-min-size 80 12

eval "$(starship init zsh)"

# eval $(thefuck --alias fuck)

ZSH_AUTOSUGGEST_HIGHLIGHT_STYLE='fg=#757575'

test -e "${HOME}/.iterm2_shell_integration.zsh" && source "${HOME}/.iterm2_shell_integration.zsh"

# NVM (defines shell functions, not just PATH — stays here)
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"
