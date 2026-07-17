{ ... }:
{
  programs.git = {
    enable = true;
    lfs.enable = true;

    # SSH commit signing (replaces the old [gpg]/[commit] block).
    signing = {
      format = "ssh";
      key = "~/.ssh/id_ed25519.pub";
      signByDefault = true;
    };

    # Aliases carried verbatim (see home/git-aliases.conf for why).
    includes = [ { path = ./git-aliases.conf; } ];

    # .gitattributes: route these file types through the mergiraf merge driver.
    attributes = [
      "*.java merge=mergiraf"
      "*.rs merge=mergiraf"
      "*.go merge=mergiraf"
      "*.js merge=mergiraf"
      "*.jsx merge=mergiraf"
      "*.json merge=mergiraf"
      "*.yml merge=mergiraf"
      "*.yaml merge=mergiraf"
      "*.toml merge=mergiraf"
      "*.html merge=mergiraf"
      "*.htm merge=mergiraf"
      "*.xhtml merge=mergiraf"
      "*.xml merge=mergiraf"
      "*.c merge=mergiraf"
      "*.cc merge=mergiraf"
      "*.h merge=mergiraf"
      "*.cpp merge=mergiraf"
      "*.hpp merge=mergiraf"
      "*.cs merge=mergiraf"
      "*.dart merge=mergiraf"
      "*.scala merge=mergiraf"
      "*.sbt merge=mergiraf"
      "*.ts merge=mergiraf"
      "*.py merge=mergiraf"
    ];

    # RFC42 freeform config (HM renamed userName/userEmail/extraConfig → settings).
    settings = {
      user = {
        name = "HernandoR";
        email = "lzhen.dev@outlook.com";
      };

      apply.whitespace = "fix";
      branch.sort = "-committerdate";
      pull.rebase = true;
      push = {
        default = "simple";
        followTags = true;
        autoSetupRemote = true;
      };

      color = {
        ui = "auto";
        branch = {
          current = "yellow reverse";
          local = "yellow";
          remote = "green";
        };
        diff = {
          meta = "yellow bold";
          frag = "magenta bold";
          old = "red";
          new = "green";
        };
        status = {
          added = "yellow";
          changed = "green";
          untracked = "cyan";
        };
      };

      init.defaultBranch = "main";

      # difftastic as the external differ (provides `difft`; see packages.nix).
      diff = {
        external = "difft";
        bin.textconv = "hexdump -v -C";
      };

      # Syntax-aware merge driver (binary in packages.nix, attributes above).
      merge.mergiraf = {
        name = "mergiraf";
        driver = "mergiraf merge --git %O %A %B -s %S -x %X -y %Y -p %P";
      };

      core = {
        whitespace = "space-before-tab,-indent-with-non-tab,trailing-space";
        trustctime = false;
        precomposeunicode = false;
        untrackedCache = true;
      };

      help.autocorrect = 1;
    };
  };
}
