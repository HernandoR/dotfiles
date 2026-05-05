def install_mac_brew(run_cmd):
    # Make sure we’re using the latest Homebrew.
    run_cmd(["brew", "update"])
    # Upgrade any already-installed formulae.
    run_cmd(["brew", "upgrade"])

    formulae = [
        "coreutils",
        "moreutils",
        "findutils",
        "gnu-sed",
        "wget",
        "rsync",
        "vim",
        "grep",
        "openssh",
        "xmake",
        "tmux",
        "thefuck",
        "tldr",
        "ack",
        "git",
        "git-lfs",
        "gs",
        "lua",
        "lynx",
        "p7zip",
        "pigz",
        "pv",
        "rename",
        "rlwrap",
        "ssh-copy-id",
        "tree",
        "vbindiff",
        "zopfli",
    ]
    for formula in formulae:
        run_cmd(["brew", "install", formula])

    # create sha256sum symlink
    import subprocess

    try:
        brew_prefix_res = subprocess.run(
            ["brew", "--prefix"], capture_output=True, text=True, check=True
        )
        brew_prefix = brew_prefix_res.stdout.strip()
        run_cmd(
            f"ln -sf {brew_prefix}/bin/gsha256sum {brew_prefix}/bin/sha256sum",
            shell=True,
        )
    except Exception as e:
        print(f"Failed to set up sha256sum symlink: {e}")

    # Font install tool
    run_cmd(
        "curl -fsSL https://raw.githubusercontent.com/HernandoR/getnf/master/install.sh | sh",
        shell=True,
    )

    casks = [
        "rsyncui",
        "visual-studio-code",
        "microsoft-edge",
        "termius",
        "texlive",
        "qspace-pro",
        "fliqlo",
    ]
    for cask in casks:
        run_cmd(["brew", "install", "--cask", cask])

    # Remove outdated versions from the cellar.
    run_cmd(["brew", "cleanup"])
