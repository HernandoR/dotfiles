sudo apt update
sudo apt -y remove libcurl4
sudo apt -y install curl git zsh rsync

./config-ohmyzsh.sh

./install-homebrew.sh

./restore_and_backup.sh restore
