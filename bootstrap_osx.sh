echo "OS: MacOS"
OSTYPE="darwin"

# for macos devices, use brew
if ! command -v curl &> /dev/null
then
    brew install curl
fi
brew install git zsh rsync