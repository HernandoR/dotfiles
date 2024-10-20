# if havent install zsh, install it first

###
# @Author: HernandoR lzhen.dev@outlook.com
# @CreateDate: Do not edit
# @LastEditors: HernandoR lzhen.dev@outlook.com
# @LastEditTime: 2024-04-04
# @Description:
#
# Copyright (c) 2024 by HernandoR lzhen.dev@outlook.com, All Rights Reserved.
###

# if [ ! command -v zsh ] &> /dev/null
# then
#     echo "zsh could not be found"
#     echo "installing zsh"
#     sudo apt -y install zsh
#     echo "zsh installed please run this script again"
#     exit 1
# fi

# chsh -s /usr/bin/zsh

if [ ! -d "./sources" ]; then
    echo "please excute this script in the dotfiles directory"
    exit 1
fi

# check if the hostmachine can curl to github

Github_Reachable=$(curl -Is https://raw.githubusercontent.com | head -n 1 | grep "200")
if [ -z $Github_Reachable ]; then
    Github_Reachable=false
else
    Github_Reachable=true
fi

if [ $Github_Reachable=true ]; then
    echo "github is reachable"
else
    echo "github is not reachable"
    echo "Using local scripts / gitee ."
fi

# read the script's directory
# DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
# DotFilesDir=DIR/../dotfiles

echo "update submodules"
git submodule init
git submodule update

# check if oh-my-zsh is installed
if [ -f ~/.oh-my-zsh/oh-my-zsh.sh ]; then
    echo "oh-my-zsh is already installed"
else
    if [ -d ~/.oh-my-zsh ]; then
        echo "oh-my-zsh was installed"
        echo "bakingup omz dir"
        rm -rf ~/oh-my-zsh.bkp
        mv ~/.oh-my-zsh ~/oh-my-zsh.bkp
    else
        echo "oh-my-zsh is not installed"
    fi
    echo "installing oh-my-zsh"
    if [ $Github_Reachable=false ]; then
        echo "installing oh-my-zsh from gitee"
        curl -fsSL https://gitee.com/mirrors/oh-my-zsh/raw/master/tools/install.sh -o ./install.sh
    else
        echo "installing oh-my-zsh from github"
        curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh -o ./install.sh
    fi
    alias exit=return
    export RUNZSH=no
    export CHSH=no
    sh ./install.sh
    unset RUNZSH
    unset CHSH
    unalias exit
    rm -f ./install.sh
fi

# install powerlevel10k, zsh-autosuggestions, zsh-syntax-highlighting
echo "installing powerlevel10k and zsh-autosuggestions and zsh-syntax-highlighting"
if [ $Github_Reachable=false ]; then
    echo "installing powerlevel10k zsh-autosuggestions, zsh-syntax-highlighting from gitee"
    git clone --depth=1 https://gitee.com/romkatv/powerlevel10k.git ${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/themes/powerlevel10k
    git clone --depth=1 https://gitee.com/githubClone/zsh-autosuggestions.git ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-autosuggestions
    git clone --depth=1 https://gitee.com/yuxiaoxi/zsh-syntax-highlighting ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-syntax-highlighting
else
    echo "installing powerlevel10k zsh-autosuggestions, zsh-syntax-highlighting from github"
    git clone --depth=1 https://github.com/romkatv/powerlevel10k.git ${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/themes/powerlevel10k
    git clone --depth=1 https://github.com/zsh-users/zsh-autosuggestions ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-autosuggestions
    git clone --depth=1 https://github.com/zsh-users/zsh-syntax-highlighting.git ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-syntax-highlighting

fi
# copy the config files
echo "copying config"
cp -f ./sources/zsh_plugins/zsh-autosuggestions.plugin.zsh ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-autosuggestions/zsh-autosuggestions.plugin.zsh
cp -f ./sources/zsh_plugins/zsh-syntax-highlighting.plugin.zsh ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.plugin.zsh
