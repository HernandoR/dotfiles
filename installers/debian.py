import os
from pathlib import Path


def install_1password(run_cmd):
    deb_path = Path("/tmp/1password-latest.deb")
    url = (
        "https://downloads.1password.com/linux/debian/amd64/stable/1password-latest.deb"
    )
    run_cmd(f"wget {url} -O {deb_path}", shell=True)
    run_cmd(["sudo", "apt", "install", "-f", "-y", str(deb_path)])
    if deb_path.exists():
        deb_path.unlink()


def install_docker(run_cmd):
    run_cmd("curl -fsSL https://get.docker.com/ | sh", shell=True)
    user = os.environ.get("USER", os.environ.get("LOGNAME"))
    run_cmd(["sudo", "groupadd", "-f", "docker"])
    if user:
        run_cmd(["sudo", "usermod", "-aG", "docker", user])
    run_cmd(["sudo", "add-apt-repository", "-y", "ppa:graphics-drivers/ppa"])
    run_cmd(["sudo", "apt-get", "update"])
    run_cmd(["sudo", "apt-get", "install", "-y", "dkms", "build-essential"])


def install_docker_rootless(run_cmd):
    run_cmd("curl -fsSL https://get.docker.com/rootless | sh", shell=True)


def install_cmdl_tools(run_cmd):
    run_cmd(["sudo", "apt-get", "update"])
    run_cmd(
        [
            "sudo",
            "apt-get",
            "install",
            "-y",
            "--no-install-recommends",
            "software-properties-common",
        ]
    )
    run_cmd(["sudo", "add-apt-repository", "-y", "ppa:deadsnakes/ppa"])
    run_cmd(["sudo", "apt-get", "update"])


def install_llvm(run_cmd, version="18", dry_run=False):
    import urllib.request

    llvm_sh_path = Path.home() / ".local" / "bin" / "llvm.sh"
    if not dry_run:
        llvm_sh_path.parent.mkdir(parents=True, exist_ok=True)
        print("  Downloading llvm.sh...")
        urllib.request.urlretrieve("https://apt.llvm.org/llvm.sh", llvm_sh_path)
        llvm_sh_path.chmod(0o755)

    print("  Running llvm.sh...")
    run_cmd([str(llvm_sh_path), version, "all"])

    print("  Setting up update-alternatives for clang...")
    alternatives = [
        ("clang", "clang", f"clang-{version}", 100),
        ("clang++", "clang++", f"clang++-{version}", None),
        ("clang-cpp", "clang-cpp", f"clang-cpp-{version}", None),
        ("clangd", "clangd", f"clangd-{version}", None),
        ("clang-format", "clang-format", f"clang-format-{version}", None),
        ("clang-tidy", "clang-tidy", f"clang-tidy-{version}", None),
        ("clang-cl", "clang-cl", f"clang-cl-{version}", None),
        ("clang-query", "clang-query", f"clang-query-{version}", None),
        ("clang-rename", "clang-rename", f"clang-rename-{version}", None),
    ]

    cmd = [
        "update-alternatives",
        "--install",
        "/usr/bin/clang",
        "clang",
        f"/usr/bin/clang-{version}",
        "100",
    ]
    for _, link, path, _ in alternatives[1:]:
        cmd.extend(["--slave", f"/usr/bin/{link}", link, f"/usr/bin/{path}"])
    run_cmd(cmd)

    bin_dir = Path("/usr/bin")
    if bin_dir.exists():
        for file in bin_dir.glob(f"*-{version}"):
            base_name = file.name.replace(f"-{version}", "")
            if not (bin_dir / base_name).exists():
                run_cmd([
                    "update-alternatives",
                    "--install",
                    f"/usr/bin/{base_name}",
                    base_name,
                    str(file),
                    "1",
                ])


def install_btm(run_cmd):
    run_cmd(["sudo", "apt-get", "install", "-y", "bottom"])


def install_fdfind(run_cmd):
    run_cmd(["sudo", "apt-get", "install", "-y", "fd-find"])


def install_cuda(run_cmd):
    run_cmd(
        "wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-ubuntu2404.pin",
        shell=True,
    )
    run_cmd(
        "sudo mv cuda-ubuntu2404.pin /etc/apt/preferences.d/cuda-repository-pin-600",
        shell=True,
    )
    deb_name = "cuda-repo-ubuntu2404-12-6-local_12.6.2-560.35.03-1_amd64.deb"
    url = f"https://developer.download.nvidia.com/compute/cuda/12.6.2/local_installers/{deb_name}"
    deb_path = Path(f"/tmp/{deb_name}")
    run_cmd(f"wget {url} -O {deb_path}", shell=True)
    run_cmd(["sudo", "dpkg", "-i", str(deb_path)])
    run_cmd(
        "sudo cp /var/cuda-repo-ubuntu2404-12-6-local/cuda-*-keyring.gpg /usr/share/keyrings/",
        shell=True,
    )
    run_cmd(["sudo", "apt-get", "update"])
    run_cmd(["sudo", "apt-get", "-y", "install", "cuda-toolkit-12-6"])
    if deb_path.exists():
        deb_path.unlink()
