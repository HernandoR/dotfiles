#!/bin/bash

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root"
  exit
fi


# list of available desktop apps
desktop_apps=(
  "vscode"
  "edge"
  "1password"
)

# parse arguments, -h, -l, -a + list of desktop apps to be installed
# if there are any apps desired but not available, print error message
#    and do not install any apps
# if there are no apps desired, print error message and do not install any apps
# if -h is passed, print help message and do not install any apps
# if -l is passed, print list of available apps and do not install any apps
# if -a is passed, install all available apps

help() {
  echo "Usage: $0 [-h] [-l] [-a] [app1 app2 ...]"
  echo "  -h: Print this help message"
  echo "  -l: Print list of available apps"
  echo "  -a: Install all available apps"
  echo "  app1 app2 ...: List of apps to install"
}

list_apps() {
  echo "Available apps:"
  for app in "${desktop_apps[@]}"; do
    echo "  $app"
  done
}

validate() {
  for app in "$@"; do
    if [[ ! " ${desktop_apps[@]} " =~ " ${app} " ]]; then
      echo "Invalid app: $app"
      list_apps
      exit 1
    fi
  done
}



# Function to install VS Code
install_vscode() {
  # Ubuntu
  if [[ -n "$(command -v apt)" ]]; then
    sudo apt update
    sudo apt install -y code
  # openSUSE
  elif [[ -n "$(command -v zypper)" ]]; then
    sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc
    sudo zypper addrepo https://packages.microsoft.com/yumrepos/vscode vscode
    sudo zypper refresh
    sudo zypper install code
  # Arch Linux
  elif [[ -n "$(command -v pacman)" ]]; then
    sudo pacman -Syu --noconfirm code
  fi
}

# Function to install Microsoft Edge
install_edge() {
  # Ubuntu
  if [[ -n "$(command -v apt)" ]]; then
    curl https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > microsoft.gpg
    install -o root -g root -m 644 microsoft.gpg /etc/apt/trusted.gpg.d/
    sh -c 'echo "deb [arch=amd64] https://packages.microsoft.com/repos/edge stable main" > /etc/apt/sources.list.d/microsoft-edge-dev.list'
    rm microsoft.gpg
    apt update
    apt install -y microsoft-edge-stable
  # openSUSE
  elif [[ -n "$(command -v zypper)" ]]; then
    sudo zypper addrepo https://packages.microsoft.com/yumrepos/edge microsoft-edge
    sudo zypper --gpg-auto-import-keys refresh -y
    sudo zypper install -y microsoft-edge-stable
  # Arch Linux
  elif [[ -n "$(command -v pacman)" ]]; then
    echo "[microsoft-edge-stable]" >> /etc/pacman.conf
    echo "Server = https://packages.microsoft.com/repos/edge/stable/community" >> /etc/pacman.conf
    pacman -Syu --noconfirm microsoft-edge-stable
  fi
}

# Function to install 1Password
install_1password() {
  # Ubuntu
  if [[ -n "$(command -v apt)" ]]; then
    curl -sS https://downloads.1password.com/linux/keys/1password.asc | sudo gpg --dearmor --output /usr/share/keyrings/1password-archive-keyring.gpg
    echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/1password-archive-keyring.gpg] https://downloads.1password.com/linux/debian/amd64 stable main' | sudo tee /etc/apt/sources.list.d/1password.list
    sudo apt update && sudo apt -y install 1password
  # openSUSE
  elif [[ -n "$(command -v zypper)" ]]; then

    sudo rpm --import https://downloads.1password.com/linux/keys/1password.asc
    sudo zypper ar https://downloads.1password.com/linux/rpm/stable/x86_64 1password
    sudo zypper install -y 1password

  # Arch Linux
  elif [[ -n "$(command -v pacman)" ]]; then
    echo "[1password]" >> /etc/pacman.conf
    echo "Server = https://downloads.1password.com/linux/arch/\$arch" >> /etc/pacman.conf
    pacman -Syu --noconfirm 1password
  fi
}

# parse arguments
while getopts ":hla" opt; do
  case ${opt} in
    h )
      help
      exit 0
      ;;
    l )
      list_apps
      exit 0
      ;;
    a )
      apps=("${desktop_apps[@]}")
      ;;
    \? )
      echo "Invalid Option: -$OPTARG" 1>&2
      help
      exit 1
      ;;
  esac
done
shift $((OPTIND -1))

# validate apps
validate "$@"
apps+=("$@")
if [[ ${#apps[@]} -eq 0 ]]; then
  echo "No apps needs to be installed"
  help
  exit 1
fi

# install apps
for app in "${apps[@]}"; do
  echo "Installing $app"
  install_$app
done