#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# ///
"""platform/setup.py — post-Home-Manager imperative steps (ADR-0007).

Run by platform/bootstrap.sh via `uv run` *after* `home-manager switch`, when
uv/python are available on the HM profile. Home Manager already owns the user
environment; this handles the imperative remainder:

    JSON(C) link map · login shell (chsh) · Claude post-setup · Linux system SW

Privilege is self-detected (Ctx.priv, live): privileged calls pass
`with_sudo=True` (or interpolate `ctx.sudo` in a shell pipeline), so sudo is
prepended only when non-root with a sudo binary; root runs bare and privileged
steps are skipped entirely when there is no way to escalate (`priv == none`).
"""
import argparse
import json
import logging
import os
import pathlib
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from installers.components import OptionalComponent, install_codegraph  # noqa: E402
from installers.context import Ctx  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dotfiles")


# --- post-HM steps -----------------------------------------------------------


def set_login_shell(ctx):
    """Make the Nix zsh the login shell (idempotent, non-fatal). Needs privilege."""
    zsh = pathlib.Path.home() / ".nix-profile" / "bin" / "zsh"
    zsh_path = str(zsh) if zsh.is_file() else (shutil.which("zsh") or "")
    if not zsh_path:
        logger.warning("zsh not found; leaving the login shell unchanged")
        return
    import pwd

    user = os.environ.get("USER") or pwd.getpwuid(os.geteuid()).pw_name
    current = pwd.getpwnam(user).pw_shell
    if current == zsh_path:
        logger.info("login shell already %s", zsh_path)
        return
    if ctx.priv == "none":
        logger.warning("no privilege: cannot chsh; run manually: chsh -s %s", zsh_path)
        return
    logger.info("setting login shell to %s", zsh_path)
    shells = pathlib.Path("/etc/shells")
    if not ctx.dry_run and shells.exists() and zsh_path not in shells.read_text().split():
        ctx.run_command(f'echo "{zsh_path}" | {ctx.sudo}tee -a /etc/shells >/dev/null', shell=True)
    if ctx.run_command(["chsh", "-s", zsh_path, user], with_sudo=True, check=False).returncode != 0:
        ctx.run_command(["usermod", "-s", zsh_path, user], with_sudo=True, check=False)


LINK_MAP_ENV = "DOTFILE_LINK_MAP_JSON"


def _load_jsonc(path):
    """Parse a JSON/JSONC file with stdlib only (the platform scripts stay
    dependency-free — see bootstrap.sh's UV_PYTHON_PREFERENCE=system). Strips
    `//` and `/* */` comments and trailing commas, then json.loads. Both passes
    are string-literal aware, so a `//`, `/*`, or `,}` *inside* a JSON string is
    preserved verbatim."""

    def _skip_string(text, i, out):
        # text[i] == '"'; copy the whole string literal (incl. escapes), return
        # the index just past the closing quote.
        out.append(text[i]); i += 1
        n = len(text)
        while i < n:
            out.append(text[i])
            if text[i] == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if text[i] == '"':
                return i + 1
            i += 1
        return i

    text = path.read_text()
    # Pass 1: strip comments.
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i = _skip_string(text, i, out); continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2; continue
        out.append(c); i += 1
    # Pass 2: drop commas that only precede whitespace then } or ].
    stage1, out, i, n = "".join(out), [], 0, len("".join(out))
    n = len(stage1)
    while i < n:
        c = stage1[i]
        if c == '"':
            i = _skip_string(stage1, i, out); continue
        if c == ",":
            j = i + 1
            while j < n and stage1[j] in " \t\r\n":
                j += 1
            if j < n and stage1[j] in "}]":
                i += 1; continue  # trailing comma
        out.append(c); i += 1
    return json.loads("".join(out))


def apply_link_map(ctx):
    """Apply a JSON(C) symlink map (ADR-0008) — the FIRST post-Home-Manager step
    (uv is on PATH by now and nothing else has run yet).

    $DOTFILE_LINK_MAP_JSON points at a JSON/JSONC file:

        {
          "links": {
            "<label>": {"source": "/abs/src", "target": "/abs/dst", "type": "dir"|"file"}
          }
        }

    - Env unset/empty  -> feature ignored.
    - Env set, file missing -> hard error (raise).
    - Both present -> each entry is validated and linked.

    A source-side *mismatch* — declared `type` != what `source` actually is, an
    unknown `type`, or a missing `source` — logs a warning and skips the entry.
    Target handling is non-destructive and idempotent:

        does not exist          -> create the symlink
        already correct symlink -> skip
        wrong / broken symlink  -> replace with the correct symlink
        real file or real dir   -> back up to a free .pre-dotfiles.bak, then link

    The `.pre-dotfiles.bak` suffix is the imperative-layer backup convention,
    distinct from Home Manager's `.backup`. Every warning is logged when hit AND
    re-emitted in a summary after the whole map is processed. No privilege."""
    raw = os.environ.get(LINK_MAP_ENV, "").strip()
    if not raw:
        return
    path = pathlib.Path(os.path.abspath(os.path.expanduser(raw)))
    if not path.is_file():
        raise FileNotFoundError(f"{LINK_MAP_ENV}={path} does not exist")
    links = _load_jsonc(path).get("links") or {}
    warnings = []

    def warn(msg):
        warnings.append(msg)
        logger.warning(msg)

    n = 0
    for label, spec in links.items():
        src = pathlib.Path(os.path.abspath(os.path.expanduser(str(spec["source"]))))
        dest = pathlib.Path(os.path.abspath(os.path.expanduser(str(spec["target"]))))
        typ = str(spec.get("type", "")).lower()
        # --- source-side validation (mismatch -> warn + skip) ---
        if typ not in ("dir", "file"):
            warn(f"[{label}] unknown type {spec.get('type')!r}; expected 'dir' or 'file' (skipped)")
            continue
        if not os.path.lexists(src):
            warn(f"[{label}] source does not exist: {src} (skipped)")
            continue
        if typ == "dir" and not src.is_dir():
            warn(f"[{label}] type=dir but source is not a directory: {src} (skipped)")
            continue
        if typ == "file" and not src.is_file():
            warn(f"[{label}] type=file but source is not a file: {src} (skipped)")
            continue
        # --- target handling (non-destructive, idempotent) ---
        if dest.is_symlink():
            if os.path.realpath(dest) == os.path.realpath(src):
                continue  # already the correct symlink -> idempotent skip
            if ctx.dry_run:
                logger.info("[%s] [DRY-RUN] would relink %s -> %s", label, dest, src)
                continue
            dest.unlink()  # wrong-target / broken symlink: no real data to back up
        elif dest.exists():
            bak = dest.with_name(dest.name + ".pre-dotfiles.bak")
            k = 1
            while os.path.lexists(bak):
                bak = dest.with_name(f"{dest.name}.pre-dotfiles.bak.{k}")
                k += 1
            warn(f"[{label}] target exists as real {'dir' if dest.is_dir() else 'file'}: "
                 f"{dest} -> backing up to {bak}")
            if ctx.dry_run:
                logger.info("[%s] [DRY-RUN] would link %s -> %s", label, dest, src)
                continue
            shutil.move(str(dest), str(bak))
        elif ctx.dry_run:
            logger.info("[%s] [DRY-RUN] would link %s -> %s", label, dest, src)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.symlink_to(src)
        logger.info("[%s] linked %s -> %s", label, dest, src)
        n += 1
    logger.info("link map %s applied: %d link(s), %d warning(s)", path, n, len(warnings))
    if warnings:
        logger.warning("link map finished with %d warning(s):", len(warnings))
        for w in warnings:
            logger.warning("  - %s", w)


def setup_runtimes(ctx):
    """Materialize every mise-managed runtime (node, rust, the npm-backed smithery
    CLI, …) declared in home/mise.nix.

    With the zsh `mise activate` integration a tool's bin only reaches PATH once it
    is actually installed — the "auto-install on first use" fires only for
    interactive commands, never for the non-interactive bash post-login script
    (which probes with `command -v`). So drive the global config to completion here
    (as ADR-0002 did for nvm), the way the first `mise install` would. No
    privilege."""
    mise = shutil.which("mise")
    if not mise:
        logger.warning("mise not on PATH; skipping runtime install")
        return
    logger.info("installing mise runtimes (node, rust, smithery, …)")
    ctx.run_command([mise, "install"], check=False)


def setup_claude(ctx):
    """Install the Claude Code CLI + CodeGraph, then write the deferred interactive
    setup (plugins/Smithery-MCP/Lark). The CLI binary and CodeGraph installs are
    fully non-interactive and run every time; the rest needs a TTY, so it is NOT
    auto-run — the user invokes it once via the `dotfiles-postsetup` shell
    function. The Smithery CLI is installed by setup_runtimes (mise npm tool), so
    it is called directly (no `npx`); only the Lark CLI still needs npx (node from
    mise). The HM zsh prints a one-line reminder while the script is still
    present. No privilege."""
    deferred = pathlib.Path.home() / ".local/share/dotfiles/post-login-setup.sh"
    if shutil.which("claude"):
        logger.info("claude CLI already installed")
    else:
        logger.info("installing Claude Code CLI")
        ctx.run_command("curl -fsSL https://claude.ai/install.sh | bash", shell=True, check=False)

    logger.info("installing codegraph")
    install_codegraph(ctx)
    # `codegraph install` wires the MCP server into Claude Code; `--yes` skips the
    # interactive agent picker. `codegraph init` is per-project and intentionally
    # not run here (a bootstrap has no project context).
    ctx.run_command(["codegraph", "install", "--target=claude", "--yes"], check=False)

    if ctx.dry_run:
        logger.info("[DRY-RUN] would write %s", deferred)
        return
    plugins = ("discuss", "implement", "dev_loop", "fetch_external_knowledge")
    # Astral's marketplace (astral-sh/claude-code-plugins) — Python tooling skills.
    astral_plugins = ("astral",)
    # Individual Smithery-registry MCP servers (qualified registry names, not npm
    # specifiers). context7 already lives in the namespace, so these are emitted
    # COMMENTED OUT — kept as a template for adding a separate server later.
    smithery_servers = ("upstash/context7-mcp",)
    lines = [
        "#!/usr/bin/env bash",
        "# Claude/Smithery/Lark setup (written by platform/setup.py). Run manually via",
        "# the `dotfiles-postsetup` shell function (needs a TTY); self-removes on",
        "# success. The Smithery CLI is a mise npm tool (installed by setup.py), so it",
        "# is called directly (no npx); only the Lark CLI still needs npx (node from mise).",
        "",
        "# Put mise-managed tools (node/npx, smithery) on PATH even when this script",
        "# is run from a shell without mise activated (e.g. a bare bash subshell).",
        'command -v mise >/dev/null 2>&1 && eval "$(mise activate bash --shims)" || true',
        "",
        "# --- Claude plugins --------------------------------------------------------",
        "claude plugin marketplace add hernandor/agent-skillset || true",
        *[f"claude plugin install {p}@agent-skillset --scope user || true" for p in plugins],
        "claude plugin marketplace add astral-sh/claude-code-plugins || true",
        *[f"claude plugin install {p}@astral-sh --scope user || true" for p in astral_plugins],
        "",
        "# --- Smithery MCP ----------------------------------------------------------",
        "if command -v smithery >/dev/null 2>&1; then",
        '  if [ -n "${SMITHERY_API_KEY:-}" ]; then',
        "    # (a/b) API key present -> offer API-key (Smithery auth) startup. The CLI",
        "    # reads SMITHERY_API_KEY from the environment automatically.",
        r'    printf "Detected SMITHERY_API_KEY. Authenticate Smithery with this API key? [Y/n] "',
        "    read -r _ans",
        '    case "$_ans" in',
        '      [Nn]*) echo "smithery: skipping API-key auth" ;;',
        '      *) smithery auth whoami || echo "smithery: API key did not resolve" ;;',
        "    esac",
        "  else",
        r'    printf "No SMITHERY_API_KEY set. Log in to Smithery interactively now? [y/N] "',
        "    read -r _ans",
        '    case "$_ans" in',
        "      [Yy]*) smithery auth login || true ;;",
        '      *) echo "smithery: skipping login" ;;',
        "    esac",
        "  fi",
        "  # (c) Namespace form: add the namespace's aggregated MCP endpoint to Claude.",
        '  _ns="$(smithery namespace show 2>/dev/null | tr -d "[:space:]")"',
        '  if [ -n "$_ns" ]; then',
        r'    printf "Add Smithery namespace \"%s\" (https://mcp.smithery.run/%s) to Claude? [Y/n] " "$_ns" "$_ns"',
        "    read -r _ans",
        '    case "$_ans" in',
        '      [Nn]*) echo "smithery: skipping namespace add" ;;',
        "      # Prefer the Smithery CLI (injects auth); fall back to Claude's own add.",
        '      *) smithery mcp add "https://mcp.smithery.run/$_ns" --name "$_ns" --client claude || claude mcp add --transport http "$_ns" "https://mcp.smithery.run/$_ns" || true ;;',
        "    esac",
        "  fi",
        "  # Add a separate registry server here (uncomment / copy this line):",
        *[f'  # smithery mcp add "{s}" --client claude || true' for s in smithery_servers],
        "else",
        r'  echo "smithery CLI not on PATH; skipping Smithery MCP (expected pre-installed)"',
        "fi",
        "",
        "# --- Lark CLI (needs npx / node from mise) ---------------------------------",
        "if command -v npx >/dev/null 2>&1; then",
        "  npx -y @larksuite/cli@latest install || true",
        "else",
        r'  echo "npx missing (mise node?); skipping Lark CLI install"',
        "fi",
        "",
        'rm -f "${BASH_SOURCE[0]}"',
    ]
    deferred.parent.mkdir(parents=True, exist_ok=True)
    deferred.write_text("\n".join(lines) + "\n")
    deferred.chmod(0o755)
    logger.info("Claude/Smithery/Lark setup written -> %s (run it with: dotfiles-postsetup)", deferred)


def run_system(ctx, spec):
    """Install opt-in Linux system components. `spec` is a comma-separated string
    of names / alias groups / the `all` keyword (see OptionalComponent.resolve)."""
    if ctx.priv == "none":
        logger.warning("no privilege: skipping system components: %s", spec)
        return
    # Each component declares its own supported_os; Component.run() skips the
    # non-applicable ones (e.g. Linux docker/cuda on macOS, macOS brew on Linux).
    selected = OptionalComponent.resolve(spec)
    # Required components (e.g. software-properties -> add-apt-repository, a
    # prerequisite for the apt-based components) are always installed first on
    # their applicable OS, whatever the spec selected. `--system none` never
    # reaches here (main() blanks the spec), so it remains a full opt-out.
    required = [n for n in OptionalComponent.required_names()
                if OptionalComponent.get(n).applicable(ctx) and n not in selected]
    names = required + selected
    if not names:
        logger.info("no valid system components in '%s' (have: %s, all)", spec, ", ".join(OptionalComponent.names()))
        return
    logger.info("system components: %s", ", ".join(names))
    for name in names:
        OptionalComponent.get(name).run(ctx)


def main():
    ap = argparse.ArgumentParser(description="Post-Home-Manager imperative setup")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--system", default="",
                    help="comma-separated components, or 'all' / 'default' / 'none' "
                         "(unset = the 'default' group)")
    ap.add_argument("--no-claude", action="store_true", help="skip Claude post-setup")
    args = ap.parse_args()

    ctx = Ctx(dry_run=args.dry_run)
    logger.info("post-HM setup | os=%s priv=%s dry_run=%s", ctx.os_type, ctx.priv, ctx.dry_run)

    # System components: --system wins; else DOTFILE_SYSTEM_COMPONENTS; else the
    # `default` group (brew on macOS). software-properties is `required` on
    # debian/ubuntu, so run_system always adds it (any non-none spec). `all` =
    # every component; `none` = skip entirely (required ones included).
    system_spec = args.system or os.environ.get("DOTFILE_SYSTEM_COMPONENTS") or "default"
    if system_spec.strip().lower() == "none":
        system_spec = ""

    # First post-HM step: apply the JSON(C) link map before anything else runs
    # (uv — hence this script — is only available after the HM switch). A missing
    # $DOTFILE_LINK_MAP_JSON file raises here and aborts the run by design.
    apply_link_map(ctx)
    set_login_shell(ctx)
    if not args.no_claude:
        setup_runtimes(ctx)
        setup_claude(ctx)
    if system_spec:
        run_system(ctx, system_spec)
    logger.info("post-HM setup complete.")


if __name__ == "__main__":
    main()
