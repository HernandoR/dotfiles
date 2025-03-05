set -xe

apt-get update

apt-get install -y --no-install-recommends \
    software-properties-common

add-apt-repository ppa:deadsnakes/ppa
apt update

# apt-get install -y --no-install-recommends \
#     python3.10 python3.10-venv python3.10-dev \
#     python-is-python3 \
#     python3-distutils

apt-get install -y --no-install-recommends \
    curl \
    git \
    jq \
    unzip \
    wget \
    rsync \
    tmux \
    axel \
    fd-find \
    bat \
    rip \
    dust \
    procs \
    lsd \

# fd-find: is find
# bat: is cat
# rip: is grep
# dust: is du
# procs: is ps
# lsd: is ls


curl -LO https://github.com/ClementTsang/bottom/releases/download/0.10.2/bottom_0.10.2-1_amd64.deb
dpkg -i bottom_0.10.2-1_amd64.deb

# uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# source /etc/../bin/env
# unset XDG_BIN_HOME
