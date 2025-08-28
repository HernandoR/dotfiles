[ -n "$PS1" ] && source ~/.bash_profile;
[ -r ~/.cloudml-cli/.profile ] && source ~/.cloudml-cli/.profile #[cml installer]
source ~/.cloudml-cli/.cml-completion.bash #[cml completion]
. "$HOME/.cargo/env"

[ ! -f "$HOME/.x-cmd.root/X" ] || . "$HOME/.x-cmd.root/X" # boot up x-cmd.
