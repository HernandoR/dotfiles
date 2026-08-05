# Sourcing order and rationale:
#   .tools      — tool env (cargo, x-cmd, nix) — must come first
#   .exports    — env vars + terminal colors — other files reference ${yellow} etc.
#   .path       — PATH additions — may depend on .tools env
#   .bash_prompt — prompt rendering — uses colors from .exports
#   .aliases    — shell aliases
#   .functions  — shell functions
#   .proxy      — proxy/mirror config — may check tool availability
#   .extra      — machine-specific overrides — runs last
#
# .bash_profile (login) sources this file after bash-specific setup (shopt, completion).
# Non-login interactive bash shells run this directly.
# The DOTFILES_SOURCED guard prevents double-sourcing from .profile.

if [ -z "${DOTFILES_SOURCED:-}" ]; then
	for file in ~/.{tools,exports,path,bash_prompt,aliases,functions,proxy,extra}; do
		[ -r "$file" ] && [ -f "$file" ] && . "$file";
	done;
	unset file;
	export DOTFILES_SOURCED=1
fi
