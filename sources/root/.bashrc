# .bashrc should avoid unguarded sourcing of .bash_profile to prevent circular references.
# .bash_profile already sources .bashrc for login shells.
# For interactive non-login shells, conditionally source ~/.bash_profile so they
# still receive the same initialization without causing recursion.
if ! shopt -q login_shell && [ -r "$HOME/.bash_profile" ]; then
    . "$HOME/.bash_profile"
fi
[ -r ~/.cloudml-cli/.profile ] && source ~/.cloudml-cli/.profile #[cml installer]
source ~/.cloudml-cli/.cml-completion.bash #[cml completion]
. "$HOME/.cargo/env"

[ ! -f "$HOME/.x-cmd.root/X" ] || . "$HOME/.x-cmd.root/X" # boot up x-cmd.
