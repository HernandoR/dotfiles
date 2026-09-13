#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Install the pinned Wanxiang Base scheme and grammar model for Squirrel."""
import argparse
import hashlib
import pathlib
import shutil
import sys
import tempfile
import tomllib
import urllib.request
import zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent
DATA = REPO / "home" / ".chezmoidata" / "rime.toml"
SOURCE = REPO / "rime"


def log(message):
    print(f"\033[1;34m==>\033[0m rime: {message}", flush=True)


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def fetch(url, expected, destination):
    urllib.request.urlretrieve(url, destination)
    actual = digest(destination)
    if actual != expected:
        raise RuntimeError(f"{destination.name}: SHA-256 {actual} != expected {expected}")


def extract_archive(archive, target):
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            path = pathlib.PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError(f"unsafe path in Wanxiang archive: {member.filename}")
            destination = target.joinpath(*path.parts)
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Refresh release-owned assets on a version change, but leave
            # generated state and any user customizations in place.
            preserve = (
                path.parts[0] in {"build", "custom"}
                or path.parts[0].endswith(".userdb")
                or path.name in {"user.yaml", "installation.yaml", ".DS_Store"}
                or path.name.endswith(".custom.yaml")
            )
            if preserve and destination.exists():
                continue
            with bundle.open(member) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)


def copy_if_changed(source, destination):
    if not destination.exists() or source.read_bytes() != destination.read_bytes():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    if sys.platform != "darwin":
        if args.plan:
            print("skip\trime: macOS only")
        return

    config = tomllib.loads(DATA.read_text())["rime"]
    target = pathlib.Path(args.state_root) / "Library" / "Rime"
    marker = target / ".dotfiles-wanxiang-version"
    needs_assets = not marker.exists() or marker.read_text().strip() != config["version"]
    custom = (
        SOURCE / "default.custom.yaml",
        SOURCE / "squirrel.custom.yaml",
        SOURCE / "wanxiang.custom.yaml",
    )
    if args.plan:
        if needs_assets:
            print("install\tRime: Wanxiang Base + wanxiang-lts-zh-hans grammar model")
        for path in custom:
            print(f"config\tRime: sync {path.name}")
        return
    if args.dry_run:
        if needs_assets:
            log(f"would install Wanxiang assets into {target}")
        return

    target.mkdir(parents=True, exist_ok=True)
    if needs_assets:
        with tempfile.TemporaryDirectory(prefix="dotfiles-rime-") as tmp:
            tmpdir = pathlib.Path(tmp)
            archive = tmpdir / "wanxiang-base.zip"
            grammar = tmpdir / "wanxiang-lts-zh-hans.gram"
            log("downloading and verifying Wanxiang Base")
            fetch(config["base_url"], config["base_sha256"], archive)
            extract_archive(archive, target)
            log("downloading and verifying Wanxiang grammar model")
            fetch(config["grammar_url"], config["grammar_sha256"], grammar)
            shutil.copy2(grammar, target / "wanxiang-lts-zh-hans.gram")
        marker.write_text(config["version"] + "\n")
    for path in custom:
        copy_if_changed(path, target / path.name)
    log(f"ready at {target}; restart Squirrel or choose Deploy")


if __name__ == "__main__":
    main()
