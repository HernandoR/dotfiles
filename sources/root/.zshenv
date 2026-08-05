# Zsh environment — sourced for ALL zsh invocations.
#
# Sourcing chain for non-interactive shells:
#   .zshenv → .tools → .exports → .path
#
# Interactive shells additionally get:
#   .bash_prompt → .aliases → .functions → .proxy → .extra
#   (then .zshrc handles zsh-specific plugins/themes)
#
# Note: the interactive guard is placed AFTER environment setup so that
# non-interactive zsh (scripts, subprocesses) still get PATH and env vars.

# ---- Environment setup (all shells) ----

for file in ~/.{tools,exports,path}; do
	[ -r "$file" ] && [ -f "$file" ] && . "$file";
done;
unset file;

# Stop here for non-interactive shells
[[ $- != *i* ]] && return

# ---- Interactive-only dotfiles ----

for file in ~/.{bash_prompt,aliases,functions,proxy,extra}; do
	[ -r "$file" ] && [ -f "$file" ] && . "$file";
done;
unset file;
