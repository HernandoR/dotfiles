# fzf-tab (Aloxaf/fzf-tab) styling — extracted from the old .zshrc.
# These zstyles are read at completion time, so they apply after the fzf-tab
# plugin is loaded (see home/shell.nix plugin ordering).

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
