conda install -n base conda-libmamba-solver
conda config --set solver libmamba
conda init "$(basename "${SHELL}")"