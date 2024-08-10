sudo apt update
if ! command -v curl &> /dev/null
then
    sudo apt -y remove libcurl4
    sudo apt -y install curl
fi

sudo apt -y aptitude install git zsh rsync

alias apt=aptitude

./config-ohmyzsh.sh

./install-homebrew.sh



./restore_and_backup.sh restore
