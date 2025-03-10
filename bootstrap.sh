#!/usr/bin/env zsh
if ! command -v brew &> /dev/null;
then
    echo "Installing Homebrew"
    ./install-homebrew.sh
fi
# if /etc/os-release does not exist, then we are on macos

if [ ! -f /etc/os-release ]; then
    echo "OS: MacOS"
    OSTYPE="darwin"
else
    OSTYPE=$(cat /etc/os-release |grep ID_LIKE | cut -d'=' -f2)
    echo "OS: $OSTYPE"
fi


if [ "$OSTYPE" = "debian" ]; then
    sudo apt update
    if ! command -v curl &> /dev/null
    then
        sudo apt -y remove libcurl4
        sudo apt -y install curl
        sudo apt -y install xclip # for tmux clipboard
    fi
    sudo apt -y install git zsh rsync
elif [ "$OSTYPE" = "darwin"]; then
    # for macos devices, use brew
    if ! command -v curl &> /dev/null
    then
        brew install curl
    fi
    brew install git zsh rsync
else
    echo "Unknown OS"
    exit 1
fi

alias apti=aptitude

./install-llvm.sh 18 all

./config-ohmyzsh.sh


./restore_and_backup.sh restore
