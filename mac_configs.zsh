

Install_homebrew_cn(){
    echo 'export HOMEBREW_API_DOMAIN=\"https://mirrors.bfsu.edu.cn/homebrew-bottles/api\"' >> ~/.exports
    echo 'export HOMEBREW_BREW_GIT_REMOTE=\"https://mirrors.bfsu.edu.cn/git/homebrew/brew.git\"' >> ~/.exports
    echo 'export HOMEBREW_CORE_GIT_REMOTE=\"https://mirrors.bfsu.edu.cn/git/homebrew/homebrew-core.git\"' >> ~/.exports
    echo 'export HOMEBREW_BOTTLE_DOMAIN=\"https://mirrors.bfsu.edu.cn/homebrew-bottles\"' >> ~/.exports
    echo 'export HOMEBREW_PIP_INDEX_URL=\"https://mirrors.bfsu.edu.cn/pypi/web/simple\"' >> ~/.exports

    export HOMEBREW_INSTALL_FROM_API=1
    export HOMEBREW_API_DOMAIN="https://mirrors.bfsu.edu.cn/homebrew-bottles/api"
    export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.bfsu.edu.cn/homebrew-bottles"
    export HOMEBREW_BREW_GIT_REMOTE="https://mirrors.bfsu.edu.cn/git/homebrew/brew.git"
    export HOMEBREW_CORE_GIT_REMOTE="https://mirrors.bfsu.edu.cn/git/homebrew/homebrew-core.git"

    # 从本镜像下载安装脚本并安装 Homebrew / Linuxbrew
    git clone --depth=1 https://mirrors.bfsu.edu.cn/git/homebrew/install.git brew-install
    /bin/bash brew-install/install.sh
    rm -rf brew-install


    (echo; echo 'eval "$(/usr/local/bin/brew shellenv)"') >> /Users/lz/.zprofile
    eval "$(/usr/local/bin/brew shellenv)"
}

homebrew_install(){
    # 也可从 GitHub 获取官方安装脚本安装 Homebrew / Linuxbrew
    /bin/bash -c "$(curl -fsSL https://github.com/Homebrew/install/raw/master/install.sh)"
}