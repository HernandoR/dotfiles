{ pkgs, lib, config, ... }:
{
  programs.fzf = {
    enable = true;
    enableZshIntegration = true; # replaces the old `source ~/.fzf.zsh`
  };

  # `z` (the old oh-my-zsh bundle) → zoxide.
  programs.zoxide = {
    enable = true;
    enableZshIntegration = true;
  };

  programs.zsh = {
    enable = true;
    enableCompletion = true;
    # autosuggestions is loaded as a plugin AFTER fzf-tab (see plugins below),
    # not via this option — HM's option sources it right after compinit, before
    # the plugin list, but fzf-tab must bind the completion widget before any
    # widget-wrapping plugin (autosuggestions) loads. syntax-highlighting stays
    # on its option because HM always sources it last, which is what it needs.
    autosuggestion.enable = false;
    syntaxHighlighting.enable = true;

    history = {
      size = 32768;
      save = 32768;
      ignoreAllDups = true; # ~ HISTCONTROL=ignoredups
      ignoreSpace = true; # ~ HISTCONTROL=ignorespace
    };

    # Load order matters (carried from the old .zshrc): completions must reach
    # fpath before compinit; fzf-tab binds the completion widget after compinit
    # and before autosuggestions / syntax-highlighting wrap widgets.
    plugins = [
      # fzf-tab loads after compinit and before autosuggestions; HM sources
      # zsh-syntax-highlighting last via syntaxHighlighting.enable.
      {
        name = "fzf-tab";
        src = pkgs.zsh-fzf-tab;
        file = "share/fzf-tab/fzf-tab.plugin.zsh";
      }
      {
        name = "zsh-autosuggestions";
        src = pkgs.zsh-autosuggestions;
        file = "share/zsh-autosuggestions/zsh-autosuggestions.zsh";
      }
    ];

    shellAliases = {
      ".." = "cd ..";
      "..." = "cd ../..";
      "...." = "cd ../../..";
      g = "git";
      ls = "ls --color=auto";
      l = "ls -lF --color=auto";
      la = "ls -lAF --color=auto";
      lsd = "ls -lF --color=auto | grep --color=never '^d'";
      grep = "grep --color=auto";
      fgrep = "fgrep --color=auto";
      egrep = "egrep --color=auto";
      week = "date +%V";
      map = "xargs -n1";
      zj = "zellij";
      reload = "exec $SHELL -l";
      path = ''echo -e ''${PATH//:/\n}'';
    };

    sessionVariables = {
      # Network-neutral only. CN mirrors are gated on DOTFILE_NETWORK_ENV in
      # envExtra below (see ADR-0007) so this config stays portable.
      HOMEBREW_NO_AUTO_UPDATE = "1";
      HOMEBREW_NO_ENV_HINTS = "1";
      NODE_REPL_HISTORY = "$HOME/.node_history";
      NODE_REPL_HISTORY_SIZE = "32768";
      NODE_REPL_MODE = "sloppy";
      PYTHONIOENCODING = "UTF-8";
      MANPAGER = "less -X";
    };

    # .zshenv (all shells): opt-in CN mirrors, gated on DOTFILE_NETWORK_ENV=CN.
    # The imperative bootstrap writes ~/.config/dotfiles/network-env when the
    # user selects the CN network; you can also export the var yourself. When
    # unset, upstream defaults are used (ADR-0007).
    envExtra = ''
      [ -r "$HOME/.config/dotfiles/network-env" ] && . "$HOME/.config/dotfiles/network-env"
      if [ "$DOTFILE_NETWORK_ENV" = "CN" ]; then
        export UV_INDEX_URL="https://mirrors.cernet.edu.cn/pypi/web/simple"
        export PIP_INDEX_URL="https://mirrors.cernet.edu.cn/pypi/web/simple"
        export RUSTUP_UPDATE_ROOT="https://mirrors.tuna.tsinghua.edu.cn/rustup/rustup"
        export RUSTUP_DIST_SERVER="https://mirrors.tuna.tsinghua.edu.cn/rustup"
      fi
    '';

    initContent = lib.mkMerge [
      # Before compinit: put zsh-completions on fpath.
      (lib.mkOrder 550 ''
        fpath+=(${pkgs.zsh-completions}/share/zsh/site-functions)
      '')

      # After plugins (default order): fzf-tab styling + interactive extras.
      (lib.mkOrder 1000 ''
        source ${./zsh/fzf-tab.zsh}
        source ${./zsh/functions.zsh}

        ZSH_AUTOSUGGEST_STRATEGY=(history)
        ZSH_AUTOSUGGEST_HIGHLIGHT_STYLE='fg=#757575'
        export GPG_TTY=$(tty)

        # rust via rustup escape hatch (mise manages rust by default).
        [ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"

        # Homebrew on macOS (kept from the old .path).
        if [ -x /opt/homebrew/bin/brew ]; then
          eval "$(/opt/homebrew/bin/brew shellenv)"
        fi

        # iTerm2 shell integration (macOS), if installed.
        [ -e "$HOME/.iterm2_shell_integration.zsh" ] && source "$HOME/.iterm2_shell_integration.zsh"

        # Machine-local, un-managed escape hatches.
        for f in "$HOME/.proxy" "$HOME/.extra"; do
          [ -r "$f" ] && . "$f"
        done
      '')
    ];
  };

  # Static PATH additions (kept from the old .path; missing dirs are harmless).
  # The two nix profile dirs are essential: standalone Home Manager does NOT put
  # them on PATH itself — it assumes Nix's own shell integration
  # (nix-daemon.sh / nix.sh) already did. That holds on a multi-user install
  # where the installer patches /etc/zshrc, but NOT in a single-user/container
  # install (HM owns the zsh files, nothing sources nix). Adding them here makes
  # the HM-installed tools (uv, jj, rg, fd, …) and `nix` reachable by name in
  # every interactive shell, on every host, independent of /etc patching.
  home.sessionPath = [
    "${config.home.homeDirectory}/bin"
    "${config.home.homeDirectory}/.local/bin"
    "${config.home.homeDirectory}/.nix-profile/bin" # HM-installed CLI tools
    "/nix/var/nix/profiles/default/bin" # `nix` on a multi-user install
    "${config.home.homeDirectory}/.pixi/bin"
    "${config.home.homeDirectory}/miniconda3/bin"
    "/usr/local/cuda/bin"
  ];
}
