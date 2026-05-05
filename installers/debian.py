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
