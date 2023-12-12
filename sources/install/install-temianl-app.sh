#!/bin/bash

source utils.sh

unset OS
unset Github_Reachable
detect_os
is_github_reachable

echo "Github_Reachable = $Github_Reachable"
echo "OS = $OS"

terminal_apps=(
    "homebrew"
    "fira_code_nerd_font"
    "fontconfig"
    "xmake"
    "command_not_found"
    "git"
    "build_essential"
    "wget"
    "curl"
    "dnsutils"
    "conda"
    "lunarvim"
    "nodejs_npm"
    "nvim"
    "lunarvim"
)

help() {
    echo "Usage: $0 [-h] [-l] [-a] [app1 app2 ...]"
    echo "  -h: Print this help message"
    echo "  -l: Print list of available apps"
    echo "  -a: Install all available apps"
    echo "  app1 app2 ...: List of apps to install"
}

list_apps() {
    echo "Available apps:"
    for app in "${terminal_apps[@]}"; do
        echo "  $app"
    done
}

validate() {
    for app in "$@"; do
        if [[ ! " ${terminal_apps[@]} " =~ " ${app} " ]]; then
            echo "Invalid app: $app"
            list_apps
            exit 1
        fi
    done
}

------------------------------------------------------------------------------------------------------------------------

# Function to install Homebrew or Linuxbrew
install_homebrew() {
    if [[ "$OS" == "macOS" ]]; then
        if ! command -v brew &> /dev/null; then
            echo "Homebrew not found. Installing Homebrew..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        else
            echo "Homebrew is already installed."
        fi
    elif [[ "$OS" == "Linux" ]]; then
        if ! command -v brew &> /dev/null; then
            echo "Homebrew not found. Installing Linuxbrew..."
            sh -c "$(curl -fsSL https://raw.githubusercontent.com/Linuxbrew/install/master/install.sh)"
        else
            echo "Linuxbrew is already installed."
        fi
    else
        echo "Homebrew or Linuxbrew is not available for this operating system."
    fi
}

# Function to install Fira Code Nerd Font
install_fira_code_nerd_font() {
    echo "Installing Fira Code Nerd Font..."
    git clone --depth 1 https://github.com/ryanoasis/nerd-fonts.git
    cd nerd-fonts
    ./install.sh FiraCode
    cd ..
    rm -rf nerd-fonts
    echo "Fira Code Nerd Font installation completed."
}

install_fontconfig() {
if [[ "$OS" != "Linux" ]]; then
    echo "fontconfig is only supported on Linux"
    return
  fi

  if command -v fc-cache > /dev/null 2>&1; then
    echo "fontconfig is already installed"
  else
    echo "Installing fontconfig..."

    if [[ -f /etc/os-release ]]; then
      linux_install  fontconfig 
    else
      echo "Unable to install fontconfig on this Linux distro"
      return 1
    fi

    echo "fontconfig installed successfully"
  fi
}
# Function to install xmake
install_xmake() {
    echo "Installing xmake..."
    if ! command -v xmake &> /dev/null; then
        curl -fsSL https://xmake.io/shget.text | sh
    else
        echo "xmake is already installed."
    fi
}

install_command_not_found() {
  if [[ "$OS" != "Linux" ]]; then
    echo "command-not-found is only supported on Linux"
    return
  fi

  if command -v command-not-found > /dev/null 2>&1; then
    echo "command-not-found is already installed"
  else
    echo "Installing command-not-found..."

    if [[ -f /etc/os-release ]]; then
      # Debian/Ubuntu
      linux_install command-not-found
    else
      echo "Unable to install command-not-found on this Linux distro"
      return 1
    fi

    echo "command-not-found installed successfully"
  fi
}

install_git() {
    echo "Installing git..."
    if ! command -v git &> /dev/null; then
        if [[ "$OS" == "macOS" ]]; then
            brew install git
        elif [[ "$OS" == "Linux" ]]; then
            sudo apt-get update
            sudo apt-get install git
        else
            echo "git installation is not supported for this operating system."
        fi
    else
        echo "git is already installed."
    fi
}

# Function to install build-essential
install_build_essential() {
    echo "Installing build-essential..."
    if [[ "$OS" == "macOS" ]]; then
        xcode-select --install
    elif [[ "$OS" == "Linux" ]]; then
        linux_install build-essential
    else
        echo "build-essential installation is not supported for this operating system."
    fi
}

# Function to install wget
install_wget() {
    echo "Installing wget..."
    if ! command -v wget &> /dev/null; then
        if [[ "$OS" == "macOS" ]]; then
            brew install wget
        elif [[ "$OS" == "Linux" ]]; then
            linux_install wget
        else
            echo "wget installation is not supported for this operating system."
        fi
    else
        echo "wget is already installed."
    fi
}

# Function to install curl
install_curl() {
    echo "Installing curl..."
    if ! command -v curl &> /dev/null; then
        if [[ "$OS" == "macOS" ]]; then
            brew install curl
        elif [[ "$OS" == "Linux" ]]; then
            sudo apt-get update
            sudo apt-get install curl
        else
            echo "curl installation is not supported for this operating system."
        fi
    else
        echo "curl is already installed."
    fi
}

# Function to install dnsutils
install_dnsutils() {
    echo "Installing dnsutils..."
    if [[ "$OS" == "macOS" ]]; then
        brew install dnsutils
    elif [[ "$OS" == "Linux" ]]; then
        linux_install dnsutils
    else
        echo "dnsutils installation is not supported for this operating system."
    fi
}

# Function to install Conda
install_conda() {
    echo "Installing Conda..."
    if ! command -v conda &> /dev/null; then
        curl -fsSL https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -o miniconda.sh
        bash miniconda.sh -b -p $HOME/miniconda
        rm miniconda.sh
    else
        echo "Conda is already installed."
    fi
}

# Function to install LunarVim
install_lunarvim() {
    echo "Installing LunarVim..."
    if ! command -v lvim &> /dev/null; then
        bash <(curl -s https://raw.githubusercontent.com/LunarVim/LunarVim/rolling/utils/installer/install.sh)
    else
        echo "LunarVim is already installed."
    fi
}

# Function to install Node.js and npm
install_nodejs_npm() {
    echo "Installing Node.js and npm..."
    if ! command -v node &> /dev/null || ! command -v npm &> /dev/null; then
        if [[ "$OS" == "macOS" ]]; then
            brew install node
        elif [[ "$OS" == "Linux" ]]; then
            curl -fsSL https://deb.nodesource.com/setup_14.x | sudo -E bash -
            linux_install nodejs
        else
            echo "Node.js and npm installation is not supported for this operating system."
        fi
    else
        echo "Node.js and npm are already installed."
    fi
}

install_nvim() {
    echo "Installing nvim..."
    if [ command -v nvim &> /dev/null ]; then
        echo "nvim is already installed."
        return 0
    fi

    if [[ "$OS" == "macOS" ]]; then
        brew install neovim
    elif [[ "$OS" == "Linux" ]]; then
        brew install neovim
    else
        echo "nvim installation is not supported for this operating system."
    fi

    # if [ ! command -v nvim &> /dev/null ] then
    #     if [[ "$OS" == "macOS" ]]; then
    #         brew install neovim
    #     elif [[ "$OS" == "Linux" ]]; then
    #         brew install neovim
    #     else
    #         echo "nvim installation is not supported for this operating system."
    #     fi
    # else
    #     echo "nvim is already installed."
    # fi
}

install_lunarvim() {
    echo "Installing lunarvim..."
    if [ command -v lvim &> /dev/null ]; then
        echo "lvim is already installed."
        return 0
    fi

    if [[ "$OS" == "macOS" ]]; then
        brew install lunarvim
    elif [[ "$OS" == "Linux" ]]; then
        LV_BRANCH='release-1.3/neovim-0.9' bash <(curl -s https://raw.githubusercontent.com/LunarVim/LunarVim/release-1.3/neovim-0.9/utils/installer/install.sh)
    else
        echo "lvim installation is not supported for this operating system."
    fi
}

------------------------------------------------------------------------------------------------------------------------

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