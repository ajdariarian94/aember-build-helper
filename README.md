# aember-build-helper

Pack your project into an **aember-ready LXC container**. Add this repository
to your project as a git submodule, describe the container in one JSON file,
and its `aember` CLI (`aember-cli/run.py build`) produces what an [aember](https://github.com/ajdariarian94/aember)
device runs:

```
aember-out/<name>/
  container.json                                  the entry for /etc/aember/containers.json
  overlay/var/lib/aember/<name>/<name>.squashfs   the read-only root file system
  overlay/var/lib/aember/<name>/lxc.container.conf
```

`aember-cli/run.py install <aember checkout>` puts it into a board's rootfs overlay
(`resources/<arch>/rootfs`), and the next `aember app pack` / `aember rpi image`
/ `aember usb image` ships it.

Python 3.10+ standard library only: nothing to install besides the tools a
source needs.

| Rootfs source                 | Needs                                       |
|-------------------------------|---------------------------------------------|
| `"dockerfile"` (your project) | docker; buildx/qemu-user for foreign `RUN`s |
| `"docker_image"` (any image)  | docker                                      |
| `"dir"` (a staged install)    | readelf when `"libs"` is set                |
| always                        | `mksquashfs` 4.6+ (squashfs-tools)          |

The aember dev container has all of them.

## Add it to your project

```bash
git submodule add https://github.com/ajdariarian94/aember-build-helper tools/aember-build-helper
tools/aember-build-helper/aember-cli/run.py init       # writes aember-container.json
# edit it, then:
tools/aember-build-helper/aember-cli/run.py build      # → aember-out/<name>/
tools/aember-build-helper/aember-cli/run.py install ../aember   # into aember's overlay
```

The CLI lives in `aember-cli/` and is called `aember`, like in aember,
aember-resources and aember-website (`aember-cli/run.py --help`). Its
commands: `init`, `check`, `build`, `install`.

In aember: `aember app pack` and `aember app launch` (or build a board image).
The container starts with the others; its output is in
`/var/log/aember-container-<name>.log` on the device.

## From a Dockerfile

Any Dockerfile: it is built for the target's platform (`--platform
linux/amd64`, `linux/arm64`, `linux/arm/v7`) and its file system exported.
The image's `ENTRYPOINT`/`CMD`, `ENV` and `WORKDIR` become the container's
command, environment and working directory unless the manifest sets them.

```json
{
  "name": "hello-docker",
  "arch": "x64-poky-linux",
  "rootfs": { "dockerfile": "Dockerfile", "context": "." },
  "env": { "GREETING": "a Dockerfile" },
  "network": "host",
  "restart_policy": "always"
}
```

`{"docker_image": "nginx:1.27-alpine"}` packs an existing image the same way.
See `examples/hello-docker/`.

## From CMake (C/C++ with the aember SDK)

Build with the aember SDK (the same compilers and glibc as the device), install
into a staging directory and pack it. `"libs"` copies the shared libraries the
binaries need (the program interpreter and every `NEEDED` library,
recursively) from the SDK's target sysroot, so the container needs no base
image at all.

```cmake
list(APPEND CMAKE_MODULE_PATH ${CMAKE_SOURCE_DIR}/tools/aember-build-helper/cmake)
include(AemberContainer)

add_executable(hello-cmake src/main.cpp)
install(TARGETS hello-cmake RUNTIME DESTINATION usr/bin)
aember_container(hello-cmake MANIFEST ${CMAKE_SOURCE_DIR}/aember-container.json
                 DEPENDS hello-cmake)
```

```json
{
  "name": "hello-cmake",
  "rootfs": { "dir": "build/aember-staging/hello-cmake" },
  "libs": { "sysroot": "/aember_ws/aember/build/aember-resources/x64-poky-linux/sdk/sysroots/core2-64-poky-linux" },
  "command": ["/usr/bin/hello-cmake"],
  "network": "isolated"
}
```

`cmake --build build --target hello-cmake-aember-container` installs the
project into `build/aember-staging/<name>/` and packs it into
`build/aember-out/<name>/` (`aember_container()` passes `--rootfs-dir`, so
the manifest's `"dir"` is only a default). Options: `OUT_DIR`, `ARCH`, `ALL`.
See `examples/hello-cmake/`. The target sysroots are `core2-64-poky-linux`
(x64), `cortexa53-poky-linux` (aarch64), `armv7at2hf-neon-poky-linux-gnueabi`
(arm32) and `riscv64imafdc-poky-linux` (riscv64); the musl variants add
`-musl` (`armv7at2hf-neon-poky-linux-musleabi` on arm32).

## A whole C++ repository: the shared project CLI

aember's own container repositories (aember-stats, aember-monitor,
aember-auth, aember-fleet's agent) share one `aember` CLI that does the SDK
download, the cross build, the unit tests and the packing. It lives here in
`project-cli/` (package `aember_project`), so a repository only keeps a
launcher, `aember-cli/run.py`, that names itself:

```python
#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "aember-build-helper" / "project-cli"))
from aember_project import Project, main  # noqa: E402

NAME = "my-app"              # = aember-container.json's "name"
RESOURCES_VERSION = "0.1.15" # aember-resources release with the SDKs
TESTS = "host"               # or "sdk": tests that need the SDK's libraries

if __name__ == "__main__":
    sys.exit(main(Project(NAME, RESOURCES_VERSION, tests=TESTS, root=ROOT)))
```

The repository's CMake project installs into a prefix (`cmake --install`)
and takes `-DBUILD_TESTS=ON` for unit tests named `*-unittest`.

```bash
aember-cli/run.py sdk -a aarch64-poky-linux     # SDK into build/aember-resources/ (or $AEMBER_RESOURCES_DIR)
aember-cli/run.py build -a aarch64-poky-linux   # cross build → build/stage/<arch>/
aember-cli/run.py pack -a aarch64-poky-linux    # → build/aember-out/<arch>/<name>/
aember-cli/run.py install -a aarch64-poky-linux ../aember
aember-cli/run.py all -a aarch64-poky-linux     # sdk + build + pack
aember-cli/run.py test [--sanitize]             # unit tests: host compiler, or the x64 SDK
```

`pack` fills in the manifest per architecture (`"arch"`, `"rootfs"` = the
stage, `"libs"` = the SDK's sysroot; `"{sysroot}/..."` in a `"files"` source
is a file from that sysroot, `"optional": true` skips it when missing) and
calls this repo's `aember build`. `AEMBER_BUILD_JOBS` caps the parallel
jobs (default: 2/3 of the CPUs).

## The manifest (`aember-container.json`)

Paths are relative to the manifest's directory.

| Key | Default | Meaning |
|-----|---------|---------|
| `name` | required | lowercase letters, digits, `-`: directory, LXC name, hostname |
| `arch` | `x64-poky-linux` | `x64-poky-linux`, `aarch64-poky-linux`, `arm-poky-linux`, `riscv64-poky-linux`, or one of their `-musl` variants (`--arch` overrides) |
| `rootfs` | required | exactly one of `dockerfile` (+ `context`), `docker_image`, `dir` |
| `files` | `[]` | `{"src", "dst", "mode"}` copied over the rootfs (replace files of the same path) |
| `libs` | none | `{"sysroot": ...}`: add the libraries the ELF files in `files` and `dir` need |
| `command` | the image's | argv of the app; required for `dir` |
| `env`, `workdir` | `{}`, none | environment and working directory of the app |
| `network` | `host` | `host` (aember's network), `isolated` (loopback only), or `{"bridge": "lxcbr0", "address": "10.0.3.20/24", "gateway": "10.0.3.1"}` |
| `devices` | `[]` | device nodes bound in if present, e.g. `/dev/fb0`, `/dev/dri` |
| `device_allow` | `[]` | `lxc.cgroup2.devices.allow` rules, e.g. `c 29:0 rwm`. Any rule makes the device filter an allow-list, so the basics (`/dev/null`, zero, random, tty, console, pts) are added too. Not needed for a privileged aember container: `devices` alone binds the node |
| `lxc` | `[]` | extra raw `lxc.*` lines |
| `restart_policy` | `always` | `no`, `on-failure`, `always` |
| `max_restart_attempts`, `restart_delay` | `5`, `5` | restarts in a row (0 = no limit), seconds between them |
| `stop_timeout`, `init` | `10`, `true` | graceful stop time; run under aember's init wrapper (passes SIGTERM on) |
| `dependencies` | `[]` | containers.json `dependencies` |
| `console_log` | `true` | keep the app's output in `/var/log/aember-container-<name>.log` (1 MB, rotated) |
| `compression` | `xz` | SquashFS compression: `xz` (mounts everywhere, also WSL), `zstd`, `gzip` |

`aember-cli/run.py check` validates it.

## How it runs on aember

aember-containerd mounts the SquashFS read-only with a RAM overlay on top at
`/var/lib/aember/containers/<name>`, binds the device's `/var/log` at
`/host-logs`, and starts the container with LXC under a small init (BusyBox,
from the host) that forwards SIGTERM, so `stop_timeout` gives your app a
graceful stop. The image gets the mount points aember needs (`/proc`, `/sys`,
`/dev`, `/tmp`, `/run`, `/host-logs`) automatically.

- The app's stdout/stderr go to the container console and, with
  `console_log`, into `/var/log/aember-container-<name>.log`. This needs an
  aember whose init wrapper sends the app's output to the console (it was
  `/dev/null` before).
- aember's container bridge (`lxcbr0`) has no NAT: a bridged container reaches
  the device, not the internet. Use `"network": "host"` for internet access.
- The container's userland is its own (Alpine, Debian, or just your binary
  and its libraries); only the kernel is shared.

## Tests

```bash
python3 -m unittest discover -s aember-cli/tests -t aember-cli    # unit tests (some need mksquashfs, gcc)
python3 -m unittest discover -s project-cli/tests -t project-cli  # the shared project CLI
tests/e2e/aember-qemu.sh /aember_ws/aember     # in the aember dev container
```

GitHub Actions runs the unit tests on every push and pull request (Python
3.10, 3.12, 3.13). The end-to-end test packs both examples, installs them into an aember
checkout's x64 overlay, packs aember and boots it in QEMU: both containers
must run, print into their console logs (read through aember's debug shell),
and the Docker one must see aember's network. The overlay is restored
afterwards.
