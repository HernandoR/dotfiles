# fzf-tab (Aloxaf/fzf-tab) styling — extracted from the old .zshrc.
# These zstyles are read at completion time, so they apply after the fzf-tab
# plugin is loaded (see home/dot_zshrc.tmpl for the load order).

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

# Use a tmux popup for the picker -- ONLY when actually inside tmux.
#
# Do not set this unconditionally. fzf-tab's -ftb-fzf decides whether it is
# using a popup by comparing the *command name* against "ftb-tmux-popup", and
# when it thinks so it skips the `echoti cud1` / `echoti cuu1` pair that moves
# the cursor off the command line before fzf draws. But ftb-tmux-popup itself
# falls back to plain `fzf` when $TMUX_PANE is unset. Outside tmux you get the
# fallback *without* the cursor compensation, so fzf's --height window is drawn
# starting on the line the cursor is on and eats it until fzf exits.
#
# $TMUX is not forwarded over ssh, so this bit the remote side only.
if [[ -n $TMUX_PANE ]]; then
  zstyle ':fzf-tab:*' fzf-command ftb-tmux-popup
  zstyle ':fzf-tab:*' popup-min-size 80 12
fi
