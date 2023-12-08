curl -L -O "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
bash Miniforge3-$(uname)-$(uname -m).sh -b
$home/miniforge3/bin/conda install -n base conda-libmamba-solver
$home/miniforge3/bin/conda config --set solver libmamba
$home/miniforge3/bin/conda init zsh
rm -f ./Miniforge3-$(uname)-$(uname -m).sh 
