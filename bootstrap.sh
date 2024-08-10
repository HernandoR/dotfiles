if ! command -v brew &> /dev/null;
then
    echo "Installing Homebrew"
    ./install-homebrew.sh
fi

if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    sudo apt update
    if ! command -v curl &> /dev/null
    then
        sudo apt -y remove libcurl4
        sudo apt -y install curl
    fi
    sudo apt -y aptitude install git zsh rsync
elif [[ "$OSTYPE" =="darwin"* ]]; then
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

./config-ohmyzsh.sh




./restore_and_backup.sh restore
