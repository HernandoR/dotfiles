# Rootless Docker + gVisor inside a Kubernetes pod

Docker for the SageMaker HyperPod / Studio dev pods (EKS, Ubuntu 24.04, root
user, no systemd). The stock `docker-rootless` system component
(`get.docker.com/rootless`) does **not** work there, and neither does a plain
`dockerd`: the pod is a container, not a VM. This directory holds what does
work and why. Everything here was derived on a live pod and verified with
`docker run`, `docker build` (legacy + BuildKit), and `docker compose` (bridge
networks, service DNS, volumes, published ports).

## Why the obvious things fail

| Symptom | Cause | What we do instead |
| --- | --- | --- |
| `systemctl start docker` — "System has not been booted with systemd" | PID 1 is `sshd`; no init system | Start the daemon from a script (`docker-rootless-start.sh`) |
| `dockerd` dies at layer extraction: `mount … operation not permitted` | No `CAP_SYS_ADMIN` in the pod | Run **rootless**: `rootlesskit` gives a user namespace where mounts are allowed |
| Rootless `dockerd` still fails: overlay mount `invalid argument` | The pod's rootfs is already overlayfs and Lustre lacks the xattrs; overlayfs cannot stack on either | `data-root` on the ext4 scratch volume (`/local/hernando/docker`) |
| runc: `error mounting "proc" … operation not permitted` | Kubernetes masks `/proc/kcore`, `/proc/keys`, …; the kernel then refuses *any* new procfs mount from a user namespace (`mount_too_revealing`) | Run containers under **gVisor** (`runsc`), which brings its own procfs and falls back to bind-mounting `/proc` |
| libnetwork: `disable_ipv6: read-only file system` | `/proc/sys` is a locked read-only bind mount | Make every network IPv6-enabled (then the sysctl already has the wanted value and is never written) and set `"ip-forward": false` |
| Service names don't resolve on user-defined networks | Docker's embedded DNS is an iptables redirect to `127.0.0.11`, which gVisor's netstack ignores | `runsc --network=host` (hostinet: host sockets inside the container netns) |
| `docker build` RUN steps lose their writes | gVisor's default `--overlay2=root:self` keeps rootfs writes inside the sandbox | `--overlay2=none` |
| BuildKit: `flag provided but not defined: -keep`, then `delete … file does not exist` | BuildKit drives `runc run --keep` and later `runc delete`; runsc has no `--keep` and auto-destroys on exit | The `runc` shim strips `--keep` and treats delete-of-missing as success |
| slirp4netns: `open: No such file or directory` | `/dev/net/tun` is absent from the pod | `mknod /dev/net/tun c 10 200` (we do have `CAP_MKNOD`) |

The real fix is upstream of this repo: `securityContext.procMount: Unmasked`
(or a privileged sidecar) on the pod spec would let plain runc work.

## Files

| File | Installed to | Role |
| --- | --- | --- |
| `setup.sh` | — | One-time, idempotent install of everything below plus apt deps, subuid/subgid, rootless extras, runsc, compose/buildx plugins, the `rootless` docker context |
| `docker-rootless-start.sh` | `/root/bin/` | Idempotent daemon start: `/dev/net/tun`, `XDG_RUNTIME_DIR=/run/user/0`, PATH with the `runc` shim first, waits for the socket |
| `runc` | `/root/.local/share/docker-rootless-bin/` | Shim that execs `runsc --ignore-cgroups --overlay2=none --network=host`; BuildKit compatibility fixes above. Set `RUNC_WRAPPER_LOG=/path` to trace calls |
| `daemon.json` | `/root/.config/docker/` | `data-root`, IPv6 pools, `ip-forward: false`, `runsc` runtime as default |

`setup.sh` also generates `/root/bin/dockerd-rootless-asroot.sh`: upstream
`dockerd-rootless.sh` with its "must not run as uid 0" guard removed (a pod
whose only user is root has no other option; rootlesskit itself only warns).

## Use

```sh
# once per pod image
sudo ./setup.sh

# after every pod restart (idempotent; put it in your shell rc if you like)
/root/bin/docker-rootless-start.sh

docker context use rootless        # done by setup.sh; socket is unix:///run/user/0/docker.sock
docker run --rm -p 8080:80 nginx:alpine
```

Logs: `/root/.local/share/docker-rootless.log`.

## Limitations

- Every container runs under gVisor in hostinet mode. Ordinary services
  (Postgres, nginx, Python apps) are fine; exotic syscalls, GPU access
  (would need nvproxy), and nested containers are not.
- No cgroups: `--memory` / `--cpus` limits are ignored.
- `/local/hernando` is an ephemeral node volume; images and volumes are lost
  when the node is replaced.
- `rootlesskit` and `runsc` live in `/root/.local/share/docker-rootless-bin`,
  not in the mise-managed docker-cli directory, so a `mise upgrade` cannot
  remove them. `dockerd`, `containerd` and the docker CLI still come from mise.
- Paths are hard-wired to `/root` and `/local/hernando`; adjust `daemon.json`
  and `setup.sh` for another user or scratch disk.
