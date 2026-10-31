#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""scripts/dsh.py — restore DeepSeek Harness (DSH) from home/.chezmoidata/dsh.toml.

DSH is the owner's agent harness, installed as the `deepseek-harness` cask
(packages.toml, macOS only) with its CLI inside the bundle. The app OWNS
$DSH_HOME at runtime, so under ADR-0014 nothing there is a chezmoi source entry;
this script restores the reviewed inventory instead (ADR-0013's ownership rule):

  1. seed profiles/<name>/{package.json,pnpm-workspace.yaml} on a fresh machine —
     without that directory `dsh plugin --profile <name> install` refuses — and
     merge ADD-ONLY into an existing profile (unknown fields and dependencies
     survive, versions reconcile, bundles keep the app's order and only grow);
  2. run `dsh plugin --profile <name> install` with the bundled pnpm when
     node_modules is missing or the package.json changed by this run;
  3. generate the HOME PATCH  $DSH_HOME/cordis.patch.yml  — the layer composed
     after every profile's patch and the one file the app never writes — from the
     [[dsh.patch]] rows plus one `insert:` row per [[dsh.mcp]] server;
  4. generate $DSH_HOME/.env (0600) from the machine-local secrets, so the patch
     can reference `process.env.<NAME>` and no token is ever in the repo.

What it does lives in home/.chezmoidata/dsh.toml — this script hardcodes no
inventory (its only constant is the MCP client package the insert rows name,
which has no per-machine dimension). `chezmoi` runs it as run_onchange_after_28-dsh; run it by hand with
`just dsh` (add `--plan` / `--dry-run` to preview). `--print-patch` renders the
patch YAML to stdout without touching anything.

Guardrails: $DSH_HOME is honoured (`$DSH_HOME`, else ~/.dsh), so a scratch home
can be rehearsed and the real one is never written when it is overridden. And
because the app rewrites the live profile at runtime, a write/install while the
DESKTOP APP IS RUNNING is skipped with a warning — probed on the Chromium
SingletonLock in ~/Library/Application Support/@deepseek-ai/dsh-desktop, since
`pgrep -f "DeepSeek Harness"` would self-match this very CLI. A scratch
$DSH_HOME is not the running app's home, so that case is allowed.
"""
import argparse
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import tomllib

# Die quietly when stdout is closed early (`… | head`) instead of ending in a
# BrokenPipeError traceback. Full rationale in scripts/context.py.
if hasattr(signal, "SIGPIPE"):
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

REPO = pathlib.Path(__file__).resolve().parent.parent
DATA = REPO / "home" / ".chezmoidata" / "dsh.toml"
DEFAULT_HOME = pathlib.Path.home() / ".dsh"
LOCK = pathlib.Path.home() / "Library" / "Application Support" / "@deepseek-ai" / "dsh-desktop" / "SingletonLock"
MCP_CLIENT = "@deepseek-ai/dsh-mcp-client"
SECRET_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SAFE_PLAIN = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")
ENV_LINE = re.compile(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


class Raw(str):
    """A YAML scalar emitted verbatim (used for the `!!js` token expressions)."""


def log(message):
    print(f"\033[1;34m==>\033[0m dsh: {message}", flush=True)


def warn(message):
    print(f"\033[1;33mwarn:\033[0m dsh: {message}", file=sys.stderr, flush=True)


def load_data():
    return tomllib.loads(DATA.read_text())["dsh"]


def dsh_home():
    return pathlib.Path(os.environ.get("DSH_HOME") or DEFAULT_HOME).expanduser()


def pretty(path):
    """`~/…` for a path under $HOME, else absolute — keeps log lines readable."""
    try:
        return f"~/{path.relative_to(pathlib.Path.home())}"
    except ValueError:
        return str(path)


def read_text(path):
    try:
        return path.read_text()
    except FileNotFoundError:
        return None


def write_file(path, text, mode=0o600):
    """Create/replace a file with `mode`. A `.env` holds a bearer token, so an
    existing file is tightened BEFORE it is truncated: truncation honours the old
    mode, and a stray 0644 `.env` would otherwise be readable for that window."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        os.chmod(path, mode)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(text)
    os.chmod(path, mode)


def app_running():
    """The desktop app's Chromium lock (`<host>-<pid>`) is the only reliable
    signal: `pgrep -f "DeepSeek Harness"` also matches this very CLI."""
    if sys.platform != "darwin":
        return False
    try:
        target = os.readlink(LOCK)
    except OSError:
        return False
    pid = target.rsplit("-", 1)[-1]
    if not pid.isdigit():
        return False
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def is_live_home(home):
    """True only for the home the running app owns; an overridden $DSH_HOME is
    a rehearsal and cannot race the app."""
    return home.resolve() == DEFAULT_HOME.resolve()


# --- secrets -----------------------------------------------------------------

def known_secrets(data, home):
    """Names the patch may reference: already in `.env`, or in the process env."""
    names = {secret["name"] for secret in data.get("secrets", []) if secret["name"] in os.environ}
    for line in (read_text(home / ".env") or "").splitlines():
        match = ENV_LINE.match(line)
        if match:
            names.add(match.group(1))
    return names


def render_env(existing, data):
    """Preserve unrelated lines/comments; update only secrets present in the
    process env. Returns (text, names this run would refresh)."""
    lines = (existing or "").splitlines()
    refreshed = []
    for secret in data.get("secrets", []):
        name, value = secret["name"], os.environ.get(secret["name"])
        if value is None:
            continue
        if "\n" in value or "\r" in value:
            warn(f"{name} contains a newline — not writing it to .env")
            continue
        line = f"{name}={value}"
        found = False
        for index, old in enumerate(lines):
            match = ENV_LINE.match(old)
            if match and match.group(1) == name:
                lines[index] = line
                found = True
                break
        if not found:
            lines.append(line)
        refreshed.append(name)
    return ("\n".join(lines) + "\n" if lines else ""), refreshed


# --- YAML rendering (the home patch) -----------------------------------------

def yaml_key(key):
    return key if SAFE_PLAIN.fullmatch(key) else json.dumps(key)


def yaml_scalar(value):
    if isinstance(value, Raw):
        return str(value)
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value if SAFE_PLAIN.fullmatch(value) else json.dumps(value)
    raise TypeError(f"unsupported YAML scalar: {value!r}")


def _emit(key, value, indent, out):
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            out.append(f"{pad}{key}: {{}}")
            return
        out.append(f"{pad}{key}:")
        for child, nested in value.items():
            _emit(yaml_key(child), nested, indent + 2, out)
    elif isinstance(value, list):
        if not value:
            out.append(f"{pad}{key}: []")
            return
        out.append(f"{pad}{key}:")
        for item in value:
            _emit_item(item, indent + 2, out)
    else:
        out.append(f"{pad}{key}: {yaml_scalar(value)}")


def _emit_item(item, indent, out):
    pad = " " * indent
    if not isinstance(item, dict):
        out.append(f"{pad}- {yaml_scalar(item)}")
        return
    if not item:
        out.append(f"{pad}- {{}}")
        return
    first = True
    for key, value in item.items():
        if not first:
            _emit(yaml_key(key), value, indent + 2, out)
            continue
        first = False
        if isinstance(value, dict) and value:
            out.append(f"{pad}- {yaml_key(key)}:")
            for child, nested in value.items():
                _emit(yaml_key(child), nested, indent + 4, out)
        elif isinstance(value, list) and value:
            out.append(f"{pad}- {yaml_key(key)}:")
            for child in value:
                _emit_item(child, indent + 4, out)
        else:
            out.append(f"{pad}- {yaml_key(key)}: {yaml_scalar(value)}")


PATCH_HEADER = [
    "# Generated by scripts/dsh.py from home/.chezmoidata/dsh.toml — edit THAT, not this file.",
    "# The home patch layer: composed after every profile's patch (ADR-0014). Secrets are",
    "# references only — the values live in $DSH_HOME/.env, never here.",
]


def mcp_rows(data, known):
    """One `insert:` row per [[dsh.mcp]] server; a tokenEnv server whose name is
    unknown is omitted and reported in the second return value."""
    rows, omitted = [], []
    for server in data.get("mcp", []):
        token_env = server.get("tokenEnv")
        if token_env and token_env not in known:
            omitted.append(token_env)
            continue
        config = {}
        for key in ("serverName", "transport", "url"):
            if key in server:
                config[key] = server[key]
        headers = dict(server.get("headers", {}))
        if token_env:
            if not SECRET_NAME.fullmatch(token_env):
                raise ValueError(f"dsh.mcp.{server.get('id')}: tokenEnv {token_env!r} is not an env var name")
            # The whole JS expression is ONE single-quoted scalar: a `!!js` tag
            # binds exactly one scalar, so `!!js "Bearer " + process.env.X` is a
            # YAML parse error ("bad indentation … at the +") in the app's own
            # patch parser. Verified against the installed app's --dump-config.
            token = Raw(f"!!js '\"Bearer \" + process.env.{token_env}'")
            headers["Authorization"] = token
            headers["X-NMEM-API-Key"] = token
        if headers:
            config["headers"] = headers
        for key in ("failOnStartupError", "toolCallTimeoutMs"):
            if key in server:
                config[key] = server[key]
        rows.append({"insert": [{"id": server["id"], "name": MCP_CLIENT, "config": config}]})
    return rows, omitted


def render_patch_rows(data, known):
    """Pure: returns (patch entries, omitted token env names)."""
    rows = []
    for entry in data.get("patch", []):
        row = {"id": entry["id"], "name": entry["name"]}
        if "config" in entry:
            row["config"] = entry["config"]
        rows.append(row)
    mcp, omitted = mcp_rows(data, known)
    return rows + mcp, omitted


def render_patch(data, known_secrets):
    """Pure render of the home patch YAML (importable by a future check)."""
    rows, _ = render_patch_rows(data, known_secrets)
    lines = list(PATCH_HEADER)
    for row in rows:
        _emit_item(row, 0, lines)
    return "\n".join(lines) + "\n"


# --- the profile seed --------------------------------------------------------

def render_workspace(workspace):
    lines = []
    for key, value in workspace.items():
        if isinstance(value, list):
            if not value:
                lines.append(f"{yaml_key(key)}: []")
                continue
            lines.append(f"{yaml_key(key)}:")
            lines.extend(f"  - {yaml_scalar(item)}" for item in value)
        elif isinstance(value, dict):
            lines.append(f"{yaml_key(key)}:")
            lines.extend(f"  {yaml_key(child)}: {yaml_scalar(nested)}" for child, nested in value.items())
        else:
            lines.append(f"{yaml_key(key)}: {yaml_scalar(value)}")
    return "\n".join(lines) + "\n"


def merge_package_json(existing, data):
    """ADD-ONLY: an app-created profile keeps its name/fields and every extra
    dependency; only declared versions and missing bundles/plugins grow in."""
    profile = data["profile"]
    if existing is None:
        return {
            "name": profile["package"],
            "private": True,
            "dependencies": dict(profile.get("plugins", {})),
            "dsh": {"profile": {"bundles": list(profile.get("bundles", []))}},
        }
    if not isinstance(existing, dict):
        raise RuntimeError("profiles: package.json is not a JSON object")
    merged = json.loads(json.dumps(existing))  # deep copy
    merged.setdefault("name", profile["package"])
    merged.setdefault("private", True)
    dependencies = merged.setdefault("dependencies", {})
    if not isinstance(dependencies, dict):
        raise RuntimeError("profiles: package.json dependencies is not an object")
    for name, version in profile.get("plugins", {}).items():
        dependencies[name] = version
    dsh = merged.setdefault("dsh", {})
    if not isinstance(dsh, dict):
        raise RuntimeError("profiles: package.json dsh is not an object")
    profiler = dsh.setdefault("profile", {})
    if not isinstance(profiler, dict):
        raise RuntimeError("profiles: package.json dsh.profile is not an object")
    bundles = profiler.setdefault("bundles", [])
    if not isinstance(bundles, list):
        raise RuntimeError("profiles: package.json dsh.profile.bundles is not a list")
    for bundle in profile.get("bundles", []):
        if bundle not in bundles:
            bundles.append(bundle)
    return merged


def run_install(cli, profile_name, profile_dir):
    # Run IN the profile: `dsh plugin` manages that directory, and pnpm resolves
    # a relative store against the working directory — inheriting chezmoi's cwd
    # could drop a `.pnpm-store` in the repo. Inside the profile it is
    # $DSH_HOME's, which the app owns anyway.
    command = [str(cli), "plugin", "--profile", profile_name, "install"]
    result = subprocess.run(command, cwd=profile_dir, capture_output=True, text=True,
                            stdin=subprocess.DEVNULL, timeout=900)
    if result.returncode != 0:
        tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-25:])
        raise RuntimeError(f"{' '.join(command)} failed ({result.returncode}):\n{tail}")


# --- planning / applying -----------------------------------------------------

class Action:
    def __init__(self, section, text, fn):
        self.section = section
        self.text = text
        self.fn = fn


def collect(data, home, cli, known):
    """Decide every action from the current state; read-only. Returns the
    actions plus the token env names whose MCP server the patch omits."""
    profile_name = data["profile"]["name"]
    profiles = home / "profiles"
    profile = profiles / profile_name
    package_json = profile / "package.json"
    workspace_yaml = profile / "pnpm-workspace.yaml"
    patch_path = home / "cordis.patch.yml"
    env_path = home / ".env"

    rows, omitted = render_patch_rows(data, known)
    patch_text = render_patch(data, known)
    patch_count, insert_count = len(data.get("patch", [])), len(rows) - len(data.get("patch", []))

    existing_json = read_text(package_json)
    try:
        existing = json.loads(existing_json) if existing_json is not None else None
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{pretty(package_json)}: invalid JSON — fix or remove it ({error})") from error
    merged = merge_package_json(existing, data)
    package_text = json.dumps(merged, indent=2) + "\n"
    package_changed = existing != merged

    existing_env = read_text(env_path)
    env_text, env_names = render_env(existing_env, data)
    env_changed = env_text != (existing_env or "")

    def mkdir(path):
        def run():
            path.mkdir(parents=True, exist_ok=True)
            os.chmod(path, 0o700)
        return run

    def write(path, text, mode):
        return lambda: write_file(path, text, mode)

    actions = []
    if not home.is_dir():
        actions.append(Action("config", f"mkdir -m 700 {pretty(home)}", mkdir(home)))
    if not profiles.is_dir():
        actions.append(Action("config", f"mkdir -m 700 {pretty(profiles)}", mkdir(profiles)))
    if not profile.is_dir():
        actions.append(Action("config", f"mkdir -m 700 {pretty(profile)}", mkdir(profile)))
    if package_changed:
        verb = "install -m 644" if existing_json is None else "write add-only"
        bundles = len(merged.get("dsh", {}).get("profile", {}).get("bundles", []))
        plugins = len(merged.get("dependencies", {}))
        actions.append(Action("config",
                              f"{verb} {pretty(package_json)} ({bundles} bundles, {plugins} pinned plugins)",
                              write(package_json, package_text, 0o644)))
    if not workspace_yaml.exists():
        actions.append(Action("config", f"install -m 644 {pretty(workspace_yaml)} (pnpm workspace seed)",
                              write(workspace_yaml, render_workspace(data["profile"].get("workspace", {})), 0o644)))
    if not (profile / "node_modules").is_dir() or package_changed:
        actions.append(Action("install",
                              f"dsh plugin --profile {profile_name} install (bundled pnpm, ~25 s)",
                              lambda: run_install(cli, profile_name, profile)))
    if read_text(patch_path) != patch_text:
        actions.append(Action("config",
                              f"install -m 600 {pretty(patch_path)} ({patch_count} patch rows, {insert_count} MCP insert)",
                              write(patch_path, patch_text, 0o600)))
    if env_changed:
        actions.append(Action("config",
                              f"install -m 600 {pretty(env_path)} (secrets: {', '.join(env_names)})",
                              write(env_path, env_text, 0o600)))
    return actions, omitted


def report_omitted(data, omitted):
    """One warning per MCP server the patch had to drop for a missing token."""
    for name in omitted:
        servers = ", ".join(server["id"] for server in data.get("mcp", [])
                            if server.get("tokenEnv") == name)
        warn(f"{name} is not set — {servers} is omitted from the patch; "
             f"set {name} in ~/.exports.local, then re-run just dsh")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan", action="store_true",
                        help="describe what would change as plan rows (section<TAB>text) and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="print every would-be action, change nothing")
    parser.add_argument("--print-patch", action="store_true",
                        help="render the home patch YAML to stdout and change nothing")
    args = parser.parse_args()

    data = load_data()
    home = dsh_home()
    known = known_secrets(data, home)

    if args.print_patch:
        _, omitted = render_patch_rows(data, known)
        report_omitted(data, omitted)
        sys.stdout.write(render_patch(data, known))
        return

    if sys.platform != "darwin":
        if args.plan:
            print("skip\tdsh: macOS only — no desktop app on headless Linux")
        return

    cli = pathlib.Path(data["app"]) / data["cli"]
    if not cli.is_file():
        warn("deepseek-harness cask not installed yet (packages.toml)")
        if args.plan:
            print("skip\tdsh: deepseek-harness cask not installed yet (packages.toml)")
        return

    actions, omitted = collect(data, home, cli, known)
    report_omitted(data, omitted)

    if args.plan:
        for action in actions:
            print(f"{action.section}\t{action.text}")
        if actions and is_live_home(home) and app_running():
            print("skip\tdsh: DSH desktop is running — quit it, then re-run just dsh")
        return
    if not actions:
        return
    if is_live_home(home) and app_running():
        warn("DSH desktop is running — quit it and re-run just dsh")
        return
    for action in actions:
        if args.dry_run:
            log(f"would {action.text}")
        else:
            log(action.text)
            action.fn()


if __name__ == "__main__":
    main()
