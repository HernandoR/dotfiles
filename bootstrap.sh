sudo apt update
if ! command -v curl &> /dev/null
then
    sudo apt -y remove libcurl4
    sudo apt -y install curl
fi

sudo apt -y install aptitude git zsh rsync

alias apt=aptitude

./install-llvm.sh 18 all

./config-ohmyzsh.sh

./install-homebrew.sh



./restore_and_backup.sh restore
