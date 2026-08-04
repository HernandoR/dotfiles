{ ... }:
{
  # direnv: enter a project's environment on `cd`. With nix-direnv below, a
  # one-line `.envrc` containing `use flake` is enough to load that project's
  # devShell — no `nix develop` subshell, and the environment leaves again on
  # `cd ..`. Per-project deps stay out of home/packages.nix (see README, "Nix —
  # per project"). New `.envrc` files are inert until `direnv allow`.
  programs.direnv = {
    enable = true;
    enableZshIntegration = true;

    # nix-direnv replaces direnv's built-in (and much slower) `use_nix` with a
    # caching implementation: the evaluated devShell is written to `.direnv/` and
    # reused until flake.nix / flake.lock change, so re-entering a project is
    # instant instead of a fresh evaluation. It also plants its own GC roots for
    # the cached shell and the flake inputs, so `nix-collect-garbage` (README,
    # "Reclaiming disk") does not delete an active project's environment — no
    # keep-outputs / keep-derivations tweak in nix.conf needed.
    #
    # HM installs it as ~/.config/direnv/lib/hm-nix-direnv.sh, which direnv
    # sources automatically; nothing to add to direnvrc.
    nix-direnv.enable = true;

    # Deliberately NOT enabling `mise.enable` (direnv's `use mise`): mise is
    # already activated globally in zsh (home/mise.nix), so its tools are on
    # PATH everywhere and the direnv-side integration would be a second, racing
    # copy of the same activation. The two coexist: both hook precmd (direnv
    # prepends `_direnv_hook`, so mise's runs last), and a devShell's copy of a
    # tool wins over the mise-managed one — measured with `just` provided by
    # both, including with a project `mise.toml` pinning a different version.
    # So a devShell that lists a tool mise also manages is what you get inside
    # that project; drop it from the devShell to fall back to mise's version.

    config.global = {
      # A first `use flake` in a project builds the whole devShell closure, which
      # is minutes, not seconds. direnv's default 5s warn_timeout turns that into
      # a "taking a while to execute" warning on every cold entry.
      warn_timeout = "1m";
      # Suppress the "export +AR +AS +CC …" wall that a nix devShell produces on
      # every entry; the "direnv: loading" line still shows what happened.
      hide_env_diff = true;
    };
  };
}
