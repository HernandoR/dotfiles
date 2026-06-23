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

antigen bundle zsh-users/zsh-syntax-highlighting
antigen bundle zsh-users/zsh-completions
antigen bundle zsh-users/zsh-autosuggestions
antigen bundle zsh-users/zsh-apple-touchbar

antigen apply

# fzf key bindings and fuzzy completion
[ -f ~/.fzf.zsh ] && source ~/.fzf.zsh

eval "$(starship init zsh)"

# eval $(thefuck --alias fuck)

ZSH_AUTOSUGGEST_HIGHLIGHT_STYLE='fg=#757575'

test -e "${HOME}/.iterm2_shell_integration.zsh" && source "${HOME}/.iterm2_shell_integration.zsh"

# NVM (defines shell functions, not just PATH — stays here)
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"
