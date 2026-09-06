#!/bin/sh
# One-time setup for rootless Docker + gVisor inside a Kubernetes pod (SageMaker
# HyperPod / Studio): no systemd, no CAP_SYS_ADMIN, masked /proc, read-only /proc/sys.
# See README.md in this directory for the reasoning. Idempotent; run as root.
#
# Requires: a docker-cli static install on PATH (dockerd, containerd, runc, ctr —
# here via `mise use -g docker-cli`), apt, and outbound HTTPS.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
BIN=/root/.local/share/docker-rootless-bin
DOCKER_VERSION=$(docker --version | sed -E 's/.*version ([0-9.]+).*/\1/')
SUBID_RANGE="root:200000:65536"

echo "== apt: uidmap slirp4netns iptables passt"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq uidmap slirp4netns iptables passt

echo "== subordinate uid/gid ranges for root"
grep -q '^root:' /etc/subuid || echo "$SUBID_RANGE" >> /etc/subuid
grep -q '^root:' /etc/subgid || echo "$SUBID_RANGE" >> /etc/subgid

echo "== docker rootless extras $DOCKER_VERSION -> $BIN"
mkdir -p "$BIN"
tmp=$(mktemp -d)
curl -sSfL "https://download.docker.com/linux/static/stable/x86_64/docker-rootless-extras-${DOCKER_VERSION}.tgz" \
  | tar xz -C "$tmp"
cp "$tmp"/docker-rootless-extras/* "$BIN"/
rm -rf "$tmp"

echo "== gVisor runsc -> $BIN"
GV=https://storage.googleapis.com/gvisor/releases/release/latest/x86_64
(cd "$BIN" && curl -sSfL -O "$GV/runsc" -O "$GV/runsc.sha512" -O "$GV/containerd-shim-runsc-v1" \
  && sha512sum -c runsc.sha512 >/dev/null && rm runsc.sha512 && chmod +x runsc containerd-shim-runsc-v1)

echo "== dockerd-rootless.sh minus its uid-0 refusal -> /root/bin/dockerd-rootless-asroot.sh"
mkdir -p /root/bin
sed '/if \[ "\$(id -u)" = "0" \]; then/,/^\tfi$/d' "$BIN/dockerd-rootless.sh" > /root/bin/dockerd-rootless-asroot.sh
chmod +x /root/bin/dockerd-rootless-asroot.sh

echo "== runc shim, daemon.json, start script"
install -m 0755 "$HERE/runc" "$BIN/runc"
mkdir -p /root/.config/docker
install -m 0644 "$HERE/daemon.json" /root/.config/docker/daemon.json
install -m 0755 "$HERE/docker-rootless-start.sh" /root/bin/docker-rootless-start.sh
mkdir -p "$(sed -nE 's/.*"data-root": *"([^"]+)".*/\1/p' "$HERE/daemon.json")"

echo "== compose + buildx CLI plugins"
mkdir -p /root/.docker/cli-plugins
latest() { curl -sS "https://api.github.com/repos/$1/releases/latest" | sed -nE 's/.*"tag_name": *"([^"]+)".*/\1/p'; }
C=$(latest docker/compose); curl -sSfL -o /root/.docker/cli-plugins/docker-compose \
  "https://github.com/docker/compose/releases/download/$C/docker-compose-linux-x86_64"
B=$(latest docker/buildx); curl -sSfL -o /root/.docker/cli-plugins/docker-buildx \
  "https://github.com/docker/buildx/releases/download/$B/buildx-$B.linux-amd64"
chmod +x /root/.docker/cli-plugins/docker-*

echo "== docker context 'rootless'"
docker context inspect rootless >/dev/null 2>&1 || docker context create rootless --docker host=unix:///run/user/0/docker.sock
docker context use rootless

echo "== start"
/root/bin/docker-rootless-start.sh
docker run --rm alpine:3.20 echo "rootless docker + gVisor: OK"
