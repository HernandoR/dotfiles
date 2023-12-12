# -b           run install in batch mode (without manual intervention),
#              it is expected the license terms are agreed upon
# -f           no error if install prefix already exists
# -h           print this help message and exit
# -p PREFIX    install prefix, defaults to /root/miniconda3, must not contain spaces.
# -s           skip running pre/post-link/install scripts
# -u           update an existing installation
# -t           run package tests after installation (may install conda-build)

curl -L -O "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
bash Miniforge3-$(uname)-$(uname -m).sh -b -u
$home/miniforge3/bin/conda init zsh
rm -f ./Miniforge3-$(uname)-$(uname -m).sh
