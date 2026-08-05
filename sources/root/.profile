# POSIX login shell entry point (bash uses .bash_profile instead).

for dir in "$HOME/bin" "$HOME/.local/bin"; do
	if [ -d "$dir" ]; then
		PATH="$dir:$PATH"
	fi
done
export PATH
