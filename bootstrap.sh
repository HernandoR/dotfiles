if ! command -v brew &> /dev/null;
then
    echo "Installing Homebrew"
    ./install-homebrew.sh
fi

sudo apt -y install aptitude git zsh rsync

alias apt=aptitude

./install-llvm.sh 18 all


./config-ohmyzsh.sh




./restore_and_backup.sh restore
