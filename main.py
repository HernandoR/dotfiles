import os
import sys
import subprocess
import platform

def run_command(cmd, check=True):
    print(f"Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    try:
        subprocess.run(cmd, check=check, shell=isinstance(cmd, str))
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {e}")
        if check:
            sys.exit(1)

def get_os_type():
    if platform.system() == "Darwin":
        return "darwin"
    elif platform.system() == "Linux":
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("ID_LIKE="):
                        return line.strip().split("=")[1].strip('"\'')
                    if line.startswith("ID=") and "debian" in line:
                        return "debian"
        except FileNotFoundError:
            pass
    return "unknown"

def bootstrap_debian():
    print("Detected Debian-based OS. Updating apt...")
    run_command(["sudo", "apt", "update"])

    # Check if curl is installed, install it and xclip if needed
    if subprocess.run(["command", "-v", "curl"], shell=True, capture_output=True).returncode != 0:
        run_command(["sudo", "apt", "-y", "remove", "libcurl4"])
        run_command(["sudo", "apt", "-y", "install", "curl"])
        run_command(["sudo", "apt", "-y", "install", "xclip"]) # for tmux clipboard

    # Install core packages
    packages = ["git", "zsh", "rsync", "aptitude"]
    run_command(["sudo", "apt", "-y", "install"] + packages)

def main():
    print("Initializing python-based dotfiles bootstrap...")
    os_type = get_os_type()
    print(f"Detected OS Type: {os_type}")

    if os_type == "darwin":
        # macOS specific setup can go here in the future
        print("macOS detected. Core package installation skipped for now.")
    elif os_type == "debian" or "ubuntu" in os_type.lower():
        bootstrap_debian()
    else:
        print(f"Unknown OS: {os_type}")
        sys.exit(1)

    # Run auxiliary installation scripts
    if os.path.exists("./install-llvm.sh"):
        run_command(["./install-llvm.sh", "18", "all"])
    else:
        print("Warning: install-llvm.sh not found.")

    if os.path.exists("./config-ohmyzsh.sh"):
        run_command(["./config-ohmyzsh.sh"])
    else:
        print("Warning: config-ohmyzsh.sh not found.")

    # Run backup/restore scripts
    # Check if python script version exists, fallback to sh
    if os.path.exists("./restore_and_backup.py"):
        run_command([sys.executable, "./restore_and_backup.py", "restore"])
    elif os.path.exists("./restore_and_backup.sh"):
        run_command(["./restore_and_backup.sh", "restore"])
    else:
        print("Warning: Neither restore_and_backup.py nor .sh found.")

    print("Bootstrap completed successfully!")

if __name__ == "__main__":
    main()
