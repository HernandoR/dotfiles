# curl -L https://gist.githubusercontent.com/HernandoR/f1d2f0be041c99bf0f7c1d0a53ac1ada/raw/install-temianl-app.sh
# curl -L https://gist.githubusercontent.com/HernandoR/f1d2f0be041c99bf0f7c1d0a53ac1ada/raw/install-desktop-app.sh
source ./install-temianl-app.sh
source ./install-desktop-app.sh

# Call the functions
detect_os
install_git
install_homebrew
install_build_essential
install_wget
install_curl
install_dnsutils

install_fira_code_nerd_font
install_xmake
install_build_essential
install_conda
# install_lunarvim
install_nodejs_npm


# install_1password
# install_edge
# install_vscode
