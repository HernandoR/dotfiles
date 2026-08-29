{ pkgs, ... }:
let
  # Key lookup for gpg.ssh.defaultKeyCommand. Git only accepts a literal
  # public key here (never a file path), so prefer whatever the agent offers
  # (1Password & co. via SSH_AUTH_SOCK) and otherwise emit the first on-disk
  # ~/.ssh/id_*.pub.
  sshSigningKeyCommand = pkgs.writeShellScript "git-ssh-signing-key" ''
    if [ -n "''${SSH_AUTH_SOCK:-}" ]; then
      key=$(ssh-add -L 2>/dev/null | head -n 1)
      case "$key" in
        ssh-* | sk-* | ecdsa-*)
          printf 'key::%s\n' "$key"
          exit 0
          ;;
      esac
    fi
    for pub in "$HOME"/.ssh/id_*.pub; do
      [ -r "$pub" ] || continue
      printf 'key::%s\n' "$(cat "$pub")"
      exit 0
    done
    echo "git-ssh-signing-key: no agent key and no ~/.ssh/id_*.pub key pair found" >&2
    exit 1
  '';

  # Signer wrapper for gpg.ssh.program. For literal keys Git always passes
  # -U ("key lives in the agent"), which fails on hosts that only have plain
  # key files. Try Git's exact invocation first; if agent signing fails and
  # the literal key matches an on-disk pair, re-sign with that pair instead.
  sshSignProgram = pkgs.writeShellScript "git-ssh-sign" ''
    # Git invokes: <program> -Y sign -n git -f <keyfile> [-U] <bufferfile>
    err=$(ssh-keygen "$@" 2>&1) && exit 0

    keyfile=
    prev=
    for a in "$@"; do
      [ "$prev" = "-f" ] && keyfile=$a
      prev=$a
    done

    if [ -n "$keyfile" ] && [ -r "$keyfile" ]; then
      want=$(awk '{print $1, $2}' "$keyfile" 2>/dev/null)
      for pub in "$HOME"/.ssh/id_*.pub; do
        [ -r "$pub" ] || continue
        if [ -n "$want" ] && [ "$want" = "$(awk '{print $1, $2}' "$pub")" ]; then
          # Signing needs the private half; the .pub only served for matching.
          priv=''${pub%.pub}
          [ -r "$priv" ] || continue
          args=()
          skip_next=0
          for a in "$@"; do
            if [ "$skip_next" = 1 ]; then
              skip_next=0
              args+=("$priv")
              continue
            fi
            case "$a" in
              -U) ;;
              -f)
                args+=(-f)
                skip_next=1
                ;;
              *) args+=("$a") ;;
            esac
          done
          exec ssh-keygen "''${args[@]}"
        fi
      done
    fi

    printf '%s\n' "$err" >&2
    exit 1
  '';
in
{
  programs.git = {
    enable = true;
    lfs.enable = true;

    # SSH commit signing, working both with an external agent (1Password et
    # al. via SSH_AUTH_SOCK) and with plain ~/.ssh/id_* key files.
    signing = {
      format = "ssh";
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

      # Serve GitHub https credentials through gh, which holds the per-host
      # token (GITHUB_TOKEN or its own login) — no credential is projected
      # here, only the delegation. Without a helper, `git credential fill`
      # returns nothing and pi-claude-marketplace's private-repo clone
      # (isomorphic-git, https-only, so SSH is not an alternative) falls into
      # its GitHub Device Flow, which in a headless `pi -p` run polls forever
      # with nobody to authorize — measured as pi hanging at startup on this
      # host over troph-team/mewtant-plugins. Scoped to github.com: other
      # hosts keep whatever they had.
      credential."https://github.com".helper = "!gh auth git-credential";

      # Agent-first key discovery with an on-disk fallback (scripts above).
      gpg.ssh = {
        defaultKeyCommand = "${sshSigningKeyCommand}";
        program = "${sshSignProgram}";
      };

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
