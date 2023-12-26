export ZSH_AUTOSUGGEST_STRATEGY=(
    history
    completion
)
# bindkey '^$' autosuggest-accept
bindkey '\t' forward-word
# Widgets that accept the entire suggestion
(( ! ${+ZSH_AUTOSUGGEST_ACCEPT_WIDGETS} )) && {
	typeset -ga ZSH_AUTOSUGGEST_ACCEPT_WIDGETS
	ZSH_AUTOSUGGEST_ACCEPT_WIDGETS=(
		forward-char
		end-of-line
		vi-forward-char
		vi-end-of-line
		vi-add-eol
	)
}

# Widgets that accept the entire suggestion and execute it
(( ! ${+ZSH_AUTOSUGGEST_EXECUTE_WIDGETS} )) && {
	typeset -ga ZSH_AUTOSUGGEST_EXECUTE_WIDGETS
	ZSH_AUTOSUGGEST_EXECUTE_WIDGETS=(
	)
}

# Widgets that accept the suggestion as far as the cursor moves
(( ! ${+ZSH_AUTOSUGGEST_PARTIAL_ACCEPT_WIDGETS} )) && {
	typeset -ga ZSH_AUTOSUGGEST_PARTIAL_ACCEPT_WIDGETS
	ZSH_AUTOSUGGEST_PARTIAL_ACCEPT_WIDGETS=(
		forward-word
		# forward-char
		emacs-forward-word
		vi-forward-word
		vi-forward-word-end
		vi-forward-blank-word
		vi-forward-blank-word-end
		vi-find-next-char
		vi-find-next-char-skip
	)
}

source ${0:A:h}/zsh-autosuggestions.zsh
