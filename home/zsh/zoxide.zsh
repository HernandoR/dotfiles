# zoxide: completion rewired for fzf-tab, plus a preview pane and `zgit`.
#
# --- Why the completion is replaced -----------------------------------------
#
# `zoxide init zsh` installs its own completer (`compdef __zoxide_z_complete z`)
# that is unusable in this config, for two independent reasons:
#
#   1. `z fo<TAB>` falls through to `_cd -/` — local subdirectories only. The
#      zoxide database is never consulted at all.
#   2. `z foo <TAB>` (note the trailing space) is the only path that queries the
#      database, and it does so by running `zoxide query --interactive` *inside*
#      the completion function, then rewriting BUFFER via a stub `compadd` plus
#      a `\e[5n` device-status-report bound to `\e[0n`. fzf-tab shadows compadd
#      to capture matches rather than add them, so the stub gets swallowed into
#      fzf-tab's own picker, two fzf instances contend for the tty, and the DSR
#      handoff never fires.
#
# Replaced below with a plain compsys completer that offers the database as
# ordinary candidates, so `z` behaves like every other completion here: fzf-tab
# renders it, with preview, group switching and the tmux popup. `zi` still
# invokes zoxide's own standalone picker, untouched.

# How many database entries `z <TAB>` offers. The list is filtered by whatever
# you have already typed *before* it is truncated, so the cap bounds the menu
# without hiding matches — `z rss<TAB>` searches the whole database and shows
# the ten best hits, not the ten best directories overall.
: ${ZOXIDE_COMPLETION_LIMIT:=10}

_zoxide_z() {
  local -a zdirs keywords
  local expl
  local ret=1

  if (( $+commands[zoxide] )); then
    # Everything typed so far, current (partial) word included, handed to zoxide
    # as keywords — the same matching `z` itself would do.
    keywords=(${(Q)words[2,CURRENT]})
    keywords=(${keywords:#})
    zdirs=(${(f)"$(zoxide query --list --exclude "${PWD}" -- "${keywords[@]}" 2>/dev/null)"})
    zdirs=(${zdirs[1,ZOXIDE_COMPLETION_LIMIT]})
  fi

  # -U skips compsys matching on purpose: zoxide already matched, and fzf
  # re-filters using the typed word (see the `query-string input` style below).
  # `zoxide query --list` is already frecency-descending, hence `sort false`.
  if (( $#zdirs )); then
    _wanted zoxide-dirs expl 'zoxide directory' compadd -U -a zdirs && ret=0
  fi

  # Second group: plain subdirectories of $PWD, so `z ../x` and `z sub` still
  # behave like cd. This one is a real file completion, so $realpath is set for
  # the preview.
  _wanted local-dirs expl 'local directory' _path_files -/ && ret=0

  return ret
}

compdef _zoxide_z z

zstyle ':completion:*:*:z:*:zoxide-dirs' sort false

# Seed fzf's query with the typed word rather than fzf-tab's default (the
# longest common prefix of the candidates, which for absolute paths is a
# useless leading "/…").
zstyle ':fzf-tab:complete:z:*' query-string input

# $realpath is only set for the local-dirs group; the zoxide group carries the
# absolute path in $word.
zstyle ':fzf-tab:complete:z:*' fzf-preview \
  'target=${realpath:-$word}; eza -1 --color=always --icons=auto "$target" 2>/dev/null || ls -1 "$target"'

# --- Preview pane for zoxide's own picker -----------------------------------
#
# Applies to every `zoxide query --interactive`, i.e. `zi` and `zgit` below.
# Parsed by zoxide with shell-word splitting, so the quoting here is literal.
export _ZO_FZF_OPTS="--preview 'eza -1 --color=always --icons=auto {} 2>/dev/null || ls -1 {}' --preview-window=right:50%:sharp --height=40% --reverse --exit-0"

# --- zgit: jump to a git repository -----------------------------------------
#
# `-e` rather than `-d`: in a linked worktree .git is a file, not a directory.
zgit() {
  local -a repos
  local dir

  for dir in ${(f)"$(zoxide query --list 2>/dev/null)"}; do
    [[ -e $dir/.git ]] && repos+=$dir
  done

  if (( ! $#repos )); then
    print -ru2 -- 'zgit: no git repositories in the zoxide database'
    return 1
  fi

  # ${(Q)${(z)...}} splits _ZO_FZF_OPTS into shell words and strips the quotes,
  # so the preview command survives as a single argument.
  dir=$(print -rl -- $repos | fzf --prompt='git repo> ' ${(Q)${(z)_ZO_FZF_OPTS}}) || return
  [[ -n $dir ]] && z -- "$dir"
}
