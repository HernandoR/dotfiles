sudo apt update

if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    if ! command -v curl &> /dev/null
    then
        sudo apt -y remove libcurl4
        sudo apt -y install curl
    fi
    sudo apt -y install git zsh rsync
fi

./config-ohmyzsh.sh

./install-homebrew.sh



./restore_and_backup.sh restore
