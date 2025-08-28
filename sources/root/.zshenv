# Add `~/bin` to the `$PATH`
export PATH="$HOME/bin:$PATH";

# stop if on a non-interactive shell
[[ $- != *i* ]] && return

# Load the shell dotfiles, and then some:
# * ~/.path can be used to extend `$PATH`.
# * ~/.extra can be used for other settings you don’t want to commit.
for file in ~/.{exports,path,functions,aliases,bash_prompt,proxy,extra}; do
	[ -r "$file" ] && [ -f "$file" ] && source "$file";
done;
unset file;
# if [ -d "$HOME/.linuxbrew/bin" ] ; then
# 	eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
# fi

. "$HOME/.cargo/env"

if [ -e /home/lz/.nix-profile/etc/profile.d/nix.sh ]; then . /home/lz/.nix-profile/etc/profile.d/nix.sh; fi # added by Nix installer
