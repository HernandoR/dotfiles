set -ex

echo "OS: MacOS"
OSTYPE="darwin"

./install-homebrew.sh

# for macos devices, use brew
if ! command -v curl &> /dev/null
then
    brew install curl
fi
brew install git zsh rsync rclone


./restore_and_backup.sh restore
