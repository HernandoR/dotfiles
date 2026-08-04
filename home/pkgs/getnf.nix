# getnf — the Nerd Fonts installer CLI (https://github.com/getnf/getnf).
#
# Not in nixpkgs (checked against the pinned nixpkgs-unstable) and upstream ships
# only .deb/.rpm, so it is packaged here. getnf is one self-contained bash script
# plus a man page: install both, then wrap it with the tools it shells out to.
#
# It downloads font tarballs from the nerd-fonts GitHub releases into
# ~/.local/share/fonts at runtime, i.e. it is an imperative escape hatch for
# "give me one more font right now". The fonts this config actually depends on
# stay declarative in ../packages.nix.
{
  lib,
  stdenvNoCC,
  fetchFromGitHub,
  makeWrapper,
  bash,
  coreutils,
  curl,
  fzf,
  gawk,
  gnutar,
  ncurses,
  xdg-user-dirs,
  xz,
}:

stdenvNoCC.mkDerivation (finalAttrs: {
  pname = "getnf";
  version = "0.3.0";

  src = fetchFromGitHub {
    owner = "getnf";
    repo = "getnf";
    tag = "v${finalAttrs.version}";
    hash = "sha256-O6xPDyovIhNKdtwMu227bRypm6EAE49aR7SMTa5LdIw=";
  };

  strictDeps = true;
  nativeBuildInputs = [ makeWrapper ];
  # Runtime interpreter: under strictDeps, patchShebangs resolves `#!/usr/bin/env
  # bash` from the *host* inputs, so bash has to be declared here or the shebang
  # survives verbatim and the script only runs where /usr/bin/env finds a bash.
  buildInputs = [ bash ];

  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    install -Dm755 getnf $out/bin/getnf
    install -Dm644 man/getnf.1 $out/share/man/man1/getnf.1

    runHook postInstall
  '';

  # curl, tar+xz, awk and the coreutils are load-bearing; `tput` (ncurses) and
  # `xdg-user-dir` are probed with `command -v` and only degrade colors / the
  # download dir when absent. `--prefix` (not `--set`) keeps the caller's PATH,
  # so `getnf -g` can still find sudo.
  postFixup = ''
    wrapProgram $out/bin/getnf \
      --prefix PATH : ${
        lib.makeBinPath (
          [
            coreutils
            curl
            fzf
            gawk
            gnutar
            ncurses
            xz
          ]
          ++ lib.optionals stdenvNoCC.hostPlatform.isLinux [ xdg-user-dirs ]
        )
      }
  '';

  meta = {
    description = "Nerd Fonts installer CLI";
    homepage = "https://github.com/getnf/getnf";
    license = lib.licenses.gpl3Only;
    mainProgram = "getnf";
    platforms = lib.platforms.unix;
  };
})
