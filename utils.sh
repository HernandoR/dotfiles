# check if the hostmachine can curl to github
is_github_reachable() {
    if [ -z $Github_Reachable ]; then
        Github_Reachable=$(curl -Is https://raw.githubusercontent.com | head -n 1 | grep "200")
        if [ ! -z $Github_Reachable ]; then
            export Github_Reachable=true
        else
            export Github_Reachable=false
        fi
    fi
    echo "Github_Reachable = $Github_Reachable"

}


# Function to detect the operating system
detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        OS="Linux"
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        OS="macOS"
    elif [[ "$OSTYPE" == "cygwin" || "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
        OS="Windows"
    else
        OS="Unknown"
    fi

    # Export the OS as a global variable
    export OS

    # Display the detected OS
    echo "Detected OS: $OS"
}

# Function to install pkgs by the platform of linux
linux_install() {
    if [[ "$OS" == "Linux" ]]; then
        if [[ -n "$(command -v apt)" ]]; then
            sudo apt update
            sudo apt install -y $@
        elif [[ -n "$(command -v zypper)" ]]; then
            sudo zypper install -y $@
        elif [[ -n "$(command -v pacman)" ]]; then
            sudo pacman -Syu --noconfirm $@
        elif [[ -n "$(command -v dnf)" ]]; then
            sudo dnf install -y $@
        elif [[ -n "$(command -v yum)" ]]; then
            sudo yum install -y $@
        else
            echo "Unable to install $@ on this Linux distro"
            return 1
        fi
    fi
}