# deprecated
echo "this script is deprecated, since miniforfe3 uses mamba as default solver"
exit 1

conda install -n base conda-libmamba-solver
conda config --set solver libmamba
conda init "$(basename "${SHELL}")"