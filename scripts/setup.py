#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""scripts/setup.py — the imperative steps that follow `chezmoi apply` (ADR-0013).

Run by chezmoi's `run_onchange_after_30-setup.sh` whenever the agent manifest,
this file or the agents/system selection changes, and by hand via `just setup`
or `uv run scripts/setup.py`. chezmoi and scripts/env_links.py already own the
files and links; this handles the remainder:

    login shell (chsh) · mise tools + nvm Node · agent toolchain (ADR-0011) · Linux system SW

Privilege is self-detected (Ctx.priv, live): privileged calls pass
`with_sudo=True`, so sudo is prepended only when non-root with a sudo binary;
root runs bare and privileged steps are skipped when there is no way to escalate.

Clearance: `build_plan()` describes every step *before* anything runs.
scripts/bootstrap.py merges it into the single full-run plan (ADR-0010). This
script never asks unless `--interactive` (or DOTFILE_INTERACTIVE=1) is given —
it is normally run by `chezmoi apply`, where a prompt would hang the apply.
`--plan` prints the plan as rows and exits.
"""
import argparse
import logging
import os
import pathlib
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agents  # noqa: E402
from components import OptionalComponent, install_codegraph  # noqa: E402
from context import Ctx  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dotfiles")

REPO_DIR = pathlib.Path(__file__).resolve().parent.parent
DEFERRED_AGENT_SETUP = pathlib.Path.home() / ".local/share/dotfiles/post-login-setup.sh"

# nmem (https://nowledge.co) — the hosted memory service that replaced the local
# `@modelcontextprotocol/server-memory` knowledge graph on 2026-09-17 (see the
# scripts/agents.py docstring). Only the URL is repo-knowledge; the bearer token is
# per-account, so it comes from $NMEM_API_KEY in ~/.exports.local (seeded by
# home/.chezmoidata/envlinks.toml) and NOTHING is written when it is absent. That is
# why nmem is here and not in agents.MCP_SERVERS: the manifest must stay committable.
NMEM_DEFAULT_URL = "https://mem.lzhen.fun:9443"

# Lark CLI wiring: brand, language and the user-token scope allowlist. The app ID
# and secret are per-organisation and this repo is public, so they come from
# $LARK_APP_ID / $LARK_APP_SECRET in ~/.exports.local, like nmem's token.
LARK_DATA = REPO_DIR / "home" / ".chezmoidata" / "lark.toml"


def _lark_settings():
    import tomllib

    return tomllib.loads(LARK_DATA.read_text())["lark"]


# --- steps -------------------------------------------------------------------------


def target_zsh():
    """The zsh the login shell should be: Homebrew's on macOS (the system one is
    older and lacks the brew site-functions), else whatever the native manager
    put on PATH."""
    if sys.platform == "darwin":
        for cand in ("/opt/homebrew/bin/zsh", "/usr/local/bin/zsh"):
            if os.access(cand, os.X_OK):
                return cand
    return shutil.which("zsh") or ""


def set_login_shell(ctx):
    """Make zsh the login shell (idempotent, non-fatal). Needs privilege."""
    zsh_path = target_zsh()
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


MISE_DATA = REPO_DIR / "home" / ".chezmoidata" / "mise.toml"
MISE_SHIMS = pathlib.Path.home() / ".local/share/mise/shims"
SYSTEM_BIN = pathlib.Path("/usr/local/bin")
# The rest of the bare system PATH: a name found here is the system's, and a link
# in /usr/local/bin (which comes first) would shadow it.
SYSTEM_DIRS = tuple(pathlib.Path(d) for d in ("/usr/local/sbin", "/usr/sbin", "/usr/bin", "/sbin", "/bin"))


class SystemLinks:
    """Every mise shim linked into /usr/local/bin, when mise.toml's
    `system_links` is on (Linux only). A shim is a symlink to mise, which
    dispatches on argv[0], so the link works from the bare system PATH of a
    process started before the login shell became zsh — the desktop app's remote
    server running `gh` for PR status, say. Never shadows or replaces what the
    system has; removes the links whose shim mise no longer provides."""

    def __init__(self):
        self.missing, self.current, self.system, self.stale = [], [], [], []
        if sys.platform != "linux" or not self._enabled() or not MISE_SHIMS.is_dir():
            return
        for shim in sorted(MISE_SHIMS.iterdir()):
            link = SYSTEM_BIN / shim.name
            if link.is_symlink() and os.readlink(link) == str(shim):
                self.current.append(link)
            elif link.exists() or link.is_symlink() or any((d / shim.name).exists() for d in SYSTEM_DIRS):
                self.system.append(link)
            else:
                self.missing.append((link, shim))
        if SYSTEM_BIN.is_dir():
            self.stale = [p for p in sorted(SYSTEM_BIN.iterdir())
                          if p.is_symlink() and os.readlink(p).startswith(f"{MISE_SHIMS}/")
                          and not p.exists()]

    @staticmethod
    def _enabled():
        import tomllib

        return bool(tomllib.loads(MISE_DATA.read_text())["mise"].get("system_links"))

    def plan(self, ctx, add):
        if not (self.missing or self.current or self.system or self.stale):
            return
        changes = len(self.missing) + len(self.stale)
        summary = (f"{SYSTEM_BIN}: link {len(self.missing)} mise shim(s), remove {len(self.stale)} "
                   f"stale; {len(self.current)} already linked, {len(self.system)} left to the system")
        if not changes:
            add("config", summary + " — unchanged")
        elif ctx.priv == "none":
            add("config", summary + ": SKIPPED (no root/sudo)")
        else:
            add("config", summary, privileged=True)

    def apply(self, ctx):
        """Idempotent and non-fatal. Needs privilege."""
        if self.system:
            logger.info("left to the system (not linked): %s", " ".join(p.name for p in self.system))
        if not (self.missing or self.stale):
            if self.current:
                logger.info("%d mise shim(s) already linked in %s", len(self.current), SYSTEM_BIN)
            return
        if ctx.priv == "none":
            logger.warning("no privilege: cannot link %d mise shim(s) into %s",
                           len(self.missing), SYSTEM_BIN)
            return
        for link in self.stale:
            ctx.run_command(["rm", "-f", str(link)], with_sudo=True, check=False)
        for link, shim in self.missing:
            ctx.run_command(["ln", "-s", str(shim), str(link)], with_sudo=True, check=False)
        logger.info("%s: linked %d mise shim(s), removed %d stale",
                    SYSTEM_BIN, len(self.missing), len(self.stale))


def setup_runtimes(ctx):
    """Runtimes and tools: mise (scripts/runtimes.py — declare missing tools, then
    `mise install`) and the Node ecosystem through nvm (scripts/node.py). Both are
    also chezmoi run_onchange scripts; calling them here makes a standalone
    `setup.py` complete on its own and costs nothing when they are current. No
    privilege."""
    for script in ("runtimes.py", "node.py"):
        cmd = ["uv", "run", "--script", str(REPO_DIR / "scripts" / script)]
        if ctx.dry_run:
            cmd.append("--dry-run")
        ctx.run_command(cmd, check=False)


def setup_agents(ctx, agent_ids):
    """Install the selected coding agents and project the ADR-0011 capability
    manifest onto each with that agent's own CLI (scripts/agents.py owns both the
    manifest and the per-agent commands). Non-interactive, so it runs on every
    bootstrap; what needs a TTY goes to the deferred script below. No privilege."""
    agents.provision(ctx, agent_ids, install_codegraph)


def write_deferred_setup(ctx, agent_ids):
    """Write the interactive remainder to ~/.local/share/dotfiles/post-login-setup.sh
    instead of running it: every step there can stop and ask (an OAuth login, a
    package-manager picker), which a bootstrap must never do. The user invokes it
    once via the `dotfiles-postsetup` zsh function; it self-removes on success and
    zsh prints a one-line reminder while the file is there. No privilege.

    gh and hf authenticate through their own CLI, which stores the credential
    under the state root (gh's hosts.yml and huggingface_hub's token files are
    env links in envlinks.toml) instead of through a GH_TOKEN / HF_TOKEN export.
    Those logins are written on every machine; the agent extras (the Lark CLI
    and nmem) only when agents are provisioned."""
    deferred = DEFERRED_AGENT_SETUP
    if ctx.dry_run:
        logger.info("[DRY-RUN] would write %s", deferred)
        return
    lark = _lark_settings()
    lark_scopes = " ".join(lark["scopes"])
    lines = [
        "#!/usr/bin/env bash",
        "# Interactive post-login setup (written by scripts/setup.py): the gh and hf",
        "# logins, plus — when agents are provisioned — the Lark CLI and nmem. Run it",
        "# via the `dotfiles-postsetup` shell function (needs a TTY); it self-removes",
        "# on success. The Lark CLI needs npx (node from nvm).",
        "#",
        "# Credentials come from each tool's own login flow, stored on the state root",
        "# through the env links (gh's hosts.yml, huggingface_hub's token files) — not",
        "# from GH_TOKEN / HF_TOKEN exports. An exported token still wins over the",
        "# login, so it is called out below and this script is kept for a re-run.",
        "#",
        "# Everything that can run unattended — marketplaces, plugins, MCP servers,",
        "# pi's declarative MCP/marketplace files and its",
        "# settings preset — is projected from scripts/agents.py during the bootstrap",
        "# (ADR-0011, ADR-0012) and is deliberately NOT repeated here.",
        "",
        "# Node (npx) comes from nvm (scripts/node.py); source it so this",
        "# works from a bare bash subshell too. mise shims cover the rest.",
        'export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"; [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" || true',
        '[ -d "$HOME/.local/share/mise/shims" ] && export PATH="$HOME/.local/share/mise/shims:$PATH"',
        "",
        "# --- gh: GitHub CLI login --------------------------------------------------",
        "# `gh auth login` stores the OAuth credential in ~/.config/gh/hosts.yml (an",
        "# env link), so it survives a container rebuild. --web is the device flow",
        "# (prints a one-time code), and --git-protocol https matches the credential",
        "# helper in home/private_dot_config/git/config.tmpl.",
        "if [ -n \"${GH_TOKEN:-}${GITHUB_TOKEN:-}\" ]; then",
        '  echo "gh: GH_TOKEN or GITHUB_TOKEN is exported — it overrides any CLI login."',
        '  echo "gh: delete that export from ~/.exports.local, open a new shell and re-run dotfiles-postsetup"',
        "  _keep_deferred=1",
        "elif ! command -v gh >/dev/null 2>&1; then",
        '  echo "gh: gh is not on PATH (it is a mise tool) — skipping the GitHub login"',
        "elif gh auth status >/dev/null 2>&1; then",
        '  echo "gh: already logged in"',
        "elif gh auth login --hostname github.com --git-protocol https --web; then",
        '  echo "gh: logged in"',
        "else",
        '  echo "gh: gh auth login did not complete; re-run dotfiles-postsetup to retry"',
        "  _keep_deferred=1",
        "fi",
        "",
        "# --- hf: Hugging Face CLI login --------------------------------------------",
        "# `hf auth login` is the device flow too; it writes the token to $HF_HOME",
        "# (~/.cache/huggingface/token, plus stored_tokens), both env links. HF_TOKEN",
        "# is still what pi's provider check reads (scripts/agents.py) and it beats the",
        "# login everywhere, so a leftover export is worth an explicit warning.",
        'if [ -n "${HF_TOKEN:-}" ]; then',
        '  echo "hf: HF_TOKEN is exported — it overrides the CLI login for every tool."',
        '  echo "hf: delete that export from ~/.exports.local, open a new shell and re-run dotfiles-postsetup"',
        "  _keep_deferred=1",
        "elif ! command -v hf >/dev/null 2>&1; then",
        '  echo "hf: hf is not on PATH (mise installs it: pipx:huggingface_hub) — skipping the Hugging Face login"',
        "elif hf auth whoami >/dev/null 2>&1; then",
        '  echo "hf: already logged in"',
        "elif hf auth login; then",
        '  echo "hf: logged in"',
        "else",
        '  echo "hf: hf auth login did not complete; re-run dotfiles-postsetup to retry"',
        "  _keep_deferred=1",
        "fi",
        "",
        "# The agent extras below (the Lark CLI and nmem) only run when agents were",
        "# provisioned; scripts/setup.py bakes that decision in as this flag.",
        f"_dotfiles_agents={'1' if agent_ids else '0'}",
        'if [ "$_dotfiles_agents" = 1 ]; then',
        "",
        "# --- Lark CLI (needs npx / node from nvm) ----------------------------------",
        "# Its installer asks which agents to wire and drops the skills into",
        f"# {agents.SHARED_SKILLS} — the loose-skills root every agent reads (ADR-0011).",
        "if command -v npx >/dev/null 2>&1; then",
        "  npx -y @larksuite/cli@latest install || true",
        "else",
        r'  echo "npx missing (mise node?); skipping Lark CLI install"',
        "fi",
        "",
        "# --- Lark CLI app + user login (home/.chezmoidata/lark.toml) ------------------",
        "# The app ID/secret come from ~/.exports.local; the login asks only for the",
        "# scope allowlist — a bare `lark-cli auth login` would grant every domain.",
        "# An existing token is never logged out here: one holding scopes beyond the",
        "# allowlist only gets a warning, since dropping it is the user's call.",
        f'_lark_scopes="{lark_scopes}"',
        'if [ -n "${LARK_OPT_OUT:-}" ]; then',
        '  echo "lark: LARK_OPT_OUT is set — skipping the Lark app config and login."',
        "elif ! command -v lark-cli >/dev/null 2>&1; then",
        '  echo "lark: lark-cli not on PATH; skipping the Lark app config and login"',
        "  _keep_deferred=1",
        "else",
        "  # Already configured: for $LARK_APP_ID when set, else for whichever app it is.",
        '  if lark-cli config show 2>/dev/null | grep -q "\\"appId\\": \\"${LARK_APP_ID:-cli_}"; then',
        "    _lark_ready=1",
        '  elif [ -z "${LARK_APP_ID:-}" ] || [ -z "${LARK_APP_SECRET:-}" ]; then',
        '    echo "lark: LARK_APP_ID / LARK_APP_SECRET are not set — leaving lark-cli unconfigured."',
        '    echo "lark: set both in ~/.exports.local, open a new shell and re-run: dotfiles-postsetup"',
        '    echo "lark: on a machine that will never use Lark, export LARK_OPT_OUT=1 to silence this for good"',
        "    _keep_deferred=1",
        f'  elif printf "%s" "${{LARK_APP_SECRET}}" | lark-cli config init --app-id "${{LARK_APP_ID}}" \\',
        f'      --brand {lark["brand"]} --lang {lark["lang"]} --app-secret-stdin >/dev/null; then',
        '    echo "lark: lark-cli configured for app ${LARK_APP_ID}"',
        "    _lark_ready=1",
        "  else",
        '    echo "lark: lark-cli config init failed; check LARK_APP_ID / LARK_APP_SECRET"',
        "    _keep_deferred=1",
        "  fi",
        '  if [ -n "${_lark_ready:-}" ]; then',
        '    if lark-cli auth check --scope "${_lark_scopes}" >/dev/null 2>&1; then',
        "      # Logged in with every allowed scope; flag anything granted beyond it.",
        '      _lark_extra="$(lark-cli auth status 2>/dev/null | ALLOWED="${_lark_scopes}" node -e \'',
        '        let s = ""; process.stdin.on("data", d => s += d).on("end", () => {',
        '          const allowed = new Set(process.env.ALLOWED.split(" "));',
        '          const user = (JSON.parse(s).identities || {}).user || {};',
        '          console.log((user.scope || "").split(" ").filter(x => x && !allowed.has(x)).length);',
        "        });' 2>/dev/null)\"",
        '      if [ "${_lark_extra:-0}" -gt 0 ] 2>/dev/null; then',
        '        echo "lark: the user token holds ${_lark_extra} scopes beyond the allowlist in lark.toml;"',
        '        echo "lark: to drop them: lark-cli auth logout, then re-run dotfiles-postsetup"',
        "      fi",
        "    elif ! lark-cli auth login --scope \"${_lark_scopes}\"; then",
        '      echo "lark: auth login did not complete; re-run dotfiles-postsetup to retry"',
        "      _keep_deferred=1",
        "    fi",
        "  fi",
        "fi",
        "unset _lark_scopes _lark_ready _lark_extra",
        "",
        "# --- nmem (hosted memory; replaces the retired local `memory` MCP server) ---",
        "# Token-gated on purpose: with no $NMEM_API_KEY there is nothing to authenticate",
        "# with, so this writes NO config at all and only says where to put one. Set it in",
        "# ~/.exports.local (NMEM_API_URL overrides the default endpoint on a machine that needs to).",
        f'_nmem_url="${{NMEM_API_URL:-{NMEM_DEFAULT_URL}}}"',
        # _keep_deferred marks a run that left nmem not-working (no token, or a
        # header that silently didn't land, or claude mcp add itself failing) so
        # post-login-setup.sh survives for a retry instead of self-removing at the
        # bottom of this script. NMEM_OPT_OUT is checked first and unconditionally,
        # so it is the one escape hatch out of every one of those branches.
        'if [ -n "${NMEM_OPT_OUT:-}" ]; then',
        # Also undoes a prior run that registered nowledge-mem before failing
        # (header didn't land, or another opt-out came after an earlier success) —
        # without this, opting out leaves that broken entry registered forever.
        '  command -v claude >/dev/null 2>&1 && claude mcp remove nowledge-mem --scope user >/dev/null 2>&1',
        '  echo "nmem: NMEM_OPT_OUT is set — nowledge-mem left unregistered and not asking again."',
        'elif [ -z "${NMEM_API_KEY:-}" ]; then',
        '  echo "nmem: NMEM_API_KEY is not set — leaving the nowledge-mem MCP server unconfigured."',
        '  echo "nmem: set NMEM_API_KEY in ~/.exports.local (export NMEM_API_KEY=nmem_...), and"',
        '  echo "nmem: NMEM_API_URL there too if ${_nmem_url} is not the right endpoint."',
        '  echo "nmem: then open a new shell and re-run: dotfiles-postsetup"',
        '  echo "nmem: on a machine that will never use nmem, export NMEM_OPT_OUT=1 to silence this for good"',
        '  _keep_deferred=1',
        "elif command -v claude >/dev/null 2>&1; then",
        '  claude mcp remove nowledge-mem --scope user >/dev/null 2>&1 || true',
        '  if claude mcp add --transport http --scope user nowledge-mem "${_nmem_url}/mcp" \\',
        '    --header "Authorization: Bearer ${NMEM_API_KEY}" \\',
        '    --header "X-NMEM-API-Key: ${NMEM_API_KEY}" \\',
        '    --header "APP: Claude Code" \\',
        '    --header "X-Nmem-Tool-Set: external-agent" \\',
        '    --header "X-Nowledge-Tool-Schema-Profile: slim" >/dev/null; then',
        # claude mcp add has shipped versions that silently drop --header while
        # still exiting 0 (anthropics/claude-code#17069); this read-back turns
        # that into a visible warning instead of a 401 the next time a tool runs.
        '    if claude mcp get nowledge-mem 2>/dev/null | grep -q "Authorization:"; then',
        '      echo "nmem: nowledge-mem -> ${_nmem_url}/mcp"',
        "    else",
        '      echo "nmem: claude mcp add reported success but the Authorization header did not land"',
        '      echo "nmem: (claude $(claude --version 2>/dev/null)); check with: claude mcp get nowledge-mem,"',
        '      echo "nmem: or export NMEM_OPT_OUT=1 to stop retrying on this machine"',
        '      _keep_deferred=1',
        "    fi",
        "  else",
        '    echo "nmem: claude mcp add failed; export NMEM_OPT_OUT=1 to stop retrying on this machine"',
        '    _keep_deferred=1',
        "  fi",
        "else",
        '  echo "nmem: claude CLI not on PATH; skipping nowledge-mem MCP"',
        "fi",
        'unset _nmem_url',
        "",
        "fi",
        'unset _dotfiles_agents',
        "",
        'if [ -n "${_keep_deferred:-}" ]; then',
        r'  echo "post-login setup: kept at ${BASH_SOURCE[0]} — rerun dotfiles-postsetup once the issues above are resolved"',
        "else",
        '  rm -f "${BASH_SOURCE[0]}"',
        "fi",
    ]
    deferred.parent.mkdir(parents=True, exist_ok=True)
    deferred.write_text("\n".join(lines) + "\n")
    deferred.chmod(0o755)
    logger.info("interactive post-login setup (gh, hf%s) written -> %s (run: dotfiles-postsetup)",
                ", Lark/nmem" if agent_ids else "", deferred)


def run_system(ctx, spec):
    """Install opt-in system components. `spec` is a comma-separated string of
    names / alias groups / `all` (see OptionalComponent.resolve)."""
    if ctx.priv == "none":
        logger.warning("no privilege: skipping system components: %s", spec)
        return
    selected = [n for n in OptionalComponent.resolve(spec)
                if OptionalComponent.get(n).applicable(ctx)]
    required = [n for n in OptionalComponent.required_names()
                if OptionalComponent.get(n).applicable(ctx) and n not in selected]
    names = required + selected
    if not names:
        logger.info("no system component applies to %s from '%s' (have: %s, all)",
                    ctx.os_type, spec, ", ".join(OptionalComponent.names()))
        return
    logger.info("system components: %s", ", ".join(names))
    for name in names:
        OptionalComponent.get(name).run(ctx)


# --- the plan --------------------------------------------------------------------


def _login_shell_plan():
    target = target_zsh() or "zsh (not installed yet — packages.toml installs it)"
    try:
        import pwd

        user = os.environ.get("USER") or pwd.getpwuid(os.geteuid()).pw_name
        current = pwd.getpwnam(user).pw_shell
    except (ImportError, KeyError):
        current = ""
    return target, current


def build_plan(ctx, system_spec, agent_ids):
    """Everything this script would do, as [(section, text, privileged)] with
    section in {"install", "config", "backup"}. Pure description."""
    items = []

    def add(section, text, privileged=False):
        items.append((section, text, privileged))

    agents.plan_items(ctx, agent_ids, add)
    extras = ", Lark/nmem" if agent_ids else ""
    add("config", f"interactive post-login setup (gh, hf{extras}) -> {DEFERRED_AGENT_SETUP} "
                  "(run later via dotfiles-postsetup)")

    if system_spec:
        if ctx.priv == "none":
            add("install", f"system components '{system_spec}': SKIPPED (no root/sudo)")
        else:
            names = [n for n in OptionalComponent.required_names()
                     if OptionalComponent.get(n).applicable(ctx)]
            names += [n for n in OptionalComponent.resolve(system_spec)
                      if n not in names and OptionalComponent.get(n).applicable(ctx)]
            if names:
                add("install", f"{len(names)} system component(s) on {ctx.os_type} (spec: {system_spec}):",
                    privileged=True)
                for n in names:
                    add("install", f"  {n} — {OptionalComponent.get(n).description}")
            else:
                add("install", f"no system component in '{system_spec}' applies to {ctx.os_type}")

    target, current = _login_shell_plan()
    if current == target:
        add("config", f"login shell already {target} — unchanged")
    elif ctx.priv == "none":
        add("config", f"login shell {current or '?'} -> {target}: SKIPPED (no root/sudo)")
    else:
        add("config", f"login shell {current or '?'} -> {target} (chsh; adds it to /etc/shells)",
            privileged=True)

    SystemLinks().plan(ctx, add)
    return items


def render_plan(items, ctx=None, network=None):
    out = []
    if ctx is not None:
        out.append("\033[1;34m==>\033[0m Plan — nothing has run yet")
        out.append(f"  os          {ctx.os_type}")
        out.append(f"  privilege   {ctx.priv}")
        out.append(f"  network     {network or os.environ.get('DOTFILE_NETWORK_ENV') or 'upstream (no CN mirrors)'}")
    sections = (
        ("install", "\033[1mwill install\033[0m"),
        ("config", "\033[1mwill write / link\033[0m"),
        ("backup", "\033[1;33mwill move your existing files aside (renamed, never deleted)\033[0m"),
    )
    for section, title in sections:
        rows = [(text, priv) for sec, text, priv in items if sec == section]
        if not rows:
            continue
        out.append(f"\n  {title}")
        for text, priv in rows:
            tag = "  \033[33m[privileged]\033[0m" if priv else ""
            bullet = f"      \033[2m{text.strip()}\033[0m" if text.startswith("  ") else f"    - {text}"
            out.append(f"{bullet}{tag}")
    print("\n".join(out))


def resolve_selection(args):
    """flag > env > default, identically here and in bootstrap.py."""
    system_spec = args.system or os.environ.get("DOTFILE_SYSTEM_COMPONENTS") or "default"
    if system_spec.strip().lower() == "none":
        system_spec = ""
    agent_spec = args.agents or os.environ.get("DOTFILE_AGENTS") or "all"
    if getattr(args, "no_claude", False):
        logger.warning("--no-claude is deprecated; use --agents=none")
        agent_spec = "none"
    return system_spec, agents.Agent.resolve(agent_spec)


def main():
    ap = argparse.ArgumentParser(description="Post-apply imperative setup (login shell, mise runtimes, agents, system components)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--system", default="",
                    help="comma-separated components, or 'all' / 'default' / 'none' (unset = 'default')")
    ap.add_argument("--agents", default="",
                    help="comma-separated agents to provision, or 'all' / 'none' (unset = all: "
                         + ", ".join(agents.Agent.names()) + ")")
    ap.add_argument("--no-claude", action="store_true", help="deprecated alias for --agents=none")
    ap.add_argument("-i", "--interactive", action="store_true",
                    help="print the plan and ask before running it (default: run unattended); "
                         "same as DOTFILE_INTERACTIVE=1")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="accepted for compatibility and already the default (nothing prompts)")
    ap.add_argument("--plan", action="store_true",
                    help="print the plan as rows (section<TAB>text[<TAB>privileged]) and exit")
    args = ap.parse_args()

    planning = args.plan
    if planning:
        logger.setLevel(logging.ERROR)
    ctx = Ctx(dry_run=args.dry_run or planning, ask=args.interactive)
    system_spec, agent_ids = resolve_selection(args)

    if planning:
        for section, text, priv in build_plan(ctx, system_spec, agent_ids):
            print(f"{section}\t{text}\t{'privileged' if priv else ''}")
        return
    if ctx.ask and not ctx.dry_run:
        render_plan(build_plan(ctx, system_spec, agent_ids), ctx=ctx)
        ctx.require_clearance()

    logger.info("setup | os=%s priv=%s dry_run=%s", ctx.os_type, ctx.priv, ctx.dry_run)
    set_login_shell(ctx)
    SystemLinks().apply(ctx)
    if agent_ids:
        setup_runtimes(ctx)
        setup_agents(ctx, agent_ids)
    # Always written: the gh and hf logins are not agent extras.
    write_deferred_setup(ctx, agent_ids)
    if system_spec:
        run_system(ctx, system_spec)
    logger.info("setup complete.")


if __name__ == "__main__":
    main()
