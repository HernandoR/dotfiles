
set -ex

export HOMEBREW_API_DOMAIN="https://mirrors.bfsu.edu.cn/homebrew-bottles/api"
export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.bfsu.edu.cn/homebrew-bottles"
export HOMEBREW_BREW_GIT_REMOTE="https://mirrors.bfsu.edu.cn/git/homebrew/brew.git"


sudo ls >/dev/null
git clone --depth=1 https://mirrors.bfsu.edu.cn/git/homebrew/install.git brew-install
export NONINTERACTIVE=1

/bin/bash brew-install/install.sh

unset NONINTERACTIVE
rm -rf brew-install
