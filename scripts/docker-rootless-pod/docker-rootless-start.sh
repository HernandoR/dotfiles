#!/bin/sh
# Start rootless dockerd on this SageMaker/EKS pod (no systemd, no CAP_SYS_ADMIN).
# Prereqs installed once: uidmap slirp4netns iptables (apt), docker-rootless-extras in the
# /root/.local/share/docker-rootless-bin, root:200000:65536 in /etc/subuid+/etc/subgid.
set -eu
export XDG_RUNTIME_DIR=/run/user/0 HOME=/root
export PATH=/root/.local/share/docker-rootless-bin:$PATH  # "runc" -> gVisor runsc wrapper
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"
# /dev/net/tun is absent in this pod; slirp4netns needs it (CAP_MKNOD is available).
[ -e /dev/net/tun ] || { mkdir -p /dev/net && mknod /dev/net/tun c 10 200 && chmod 666 /dev/net/tun; }
if docker -H unix://$XDG_RUNTIME_DIR/docker.sock info >/dev/null 2>&1; then
  echo "rootless dockerd already running at unix://$XDG_RUNTIME_DIR/docker.sock"; exit 0
fi
rm -rf "$XDG_RUNTIME_DIR/dockerd-rootless" "$XDG_RUNTIME_DIR/docker.sock"
LOG=/root/.local/share/docker-rootless.log
nohup /root/bin/dockerd-rootless-asroot.sh >"$LOG" 2>&1 &
for i in $(seq 1 30); do
  docker -H unix://$XDG_RUNTIME_DIR/docker.sock info >/dev/null 2>&1 && { echo "rootless dockerd up (log: $LOG)"; exit 0; }
  sleep 1
done
echo "dockerd failed to start; see $LOG" >&2; tail -20 "$LOG" >&2; exit 1
