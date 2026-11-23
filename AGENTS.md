# AGENTS.md

Guidance for AI coding agents (Claude Code, Copilot, Codex, …) working in
**aember-build-helper**.

## What this repo is

A tool that application developers add to *their* project (as a git
submodule) to pack it into an LXC container that
[aember](https://github.com/ajdariarian94/aember) runs. aember is a C++23
PID 1 for container appliances; its `aember-containerd` service starts the
containers listed in `/etc/aember/containers.json`. Sibling repos:
`../aember` (the init system and its CLI) and `../aember-resources` (kernel,
BusyBox, LXC, SDK).

The helper's whole job is to produce, for a container `<name>`:

```
aember-out/<name>/container.json                                 → containers.json entry
aember-out/<name>/overlay/var/lib/aember/<name>/<name>.squashfs  → read-only rootfs
aember-out/<name>/overlay/var/lib/aember/<name>/lxc.container.conf
```

and to merge that into an aember board overlay (`aember-cli/run.py install`).

Repository: <https://github.com/ajdariarian94/aember-build-helper>
(public). Like the sibling repos: branch off `main` and merge through a PR.

## Layout

```
aember-cli/                      the `aember` CLI (same place and name as in the sibling repos)
  run.py                         launcher (puts aember-cli/ first on sys.path; no install)
  pyproject.toml                 script `aember`; no dependencies
  aember/cli.py                  argparse: init, check, build, install
  aember/manifest.py             aember-container.json → Manifest (validation, defaults)
  aember/contract.py             aember's contract: paths, lxc.container.conf, containers.json entry
  aember/rootfs.py               rootfs as ONE tar stream → `mksquashfs - out -tar`
  aember/libs.py                 NEEDED + interpreter resolution from a sysroot (readelf)
  aember/install.py              copy into an overlay, merge containers.json
  tests/test_*.py                unittest (stdlib); squashfs/gcc tests skip without the tools
project-cli/aember_project/       shared CLI of the C++ container repos (aember-stats, -monitor,
                                 -auth, fleet's agent): sdk, build, pack, install, test, all
  project.py                     Project(name, resources_version, tests, root) from their run.py
  sdk.py / build.py / cli.py     SDK download + paths, cmake in the SDK, tests, pack via aember-cli
project-cli/tests/               unittest of the shared CLI (no SDK needed)
cmake/AemberContainer.cmake      aember_container(): cmake --install to staging + run.py build
examples/hello-docker/           Dockerfile source (Alpine + a shell script)
examples/hello-cmake/            C++23 + aember SDK + libs from the sysroot
tests/e2e/aember-qemu.sh         both examples into aember, QEMU boot, checks
```

## Rules

- **Python 3.10+ standard library only.** The tool runs from a submodule on
  developer machines and in CI with no venv. No third-party imports, also
  not in tests.
- **No root.** The rootfs is streamed as tar into `mksquashfs -tar`
  (squashfs-tools ≥ 4.6), so owners and modes (from Docker images) survive
  without extracting anything to disk. Don't switch to extract + mksquashfs
  of a directory: it needs root for ownership and doubles the disk use.
- Files from `"files"`, `"libs"` and `"dir"` sources are owned by root in
  the image; Docker sources keep their owners.
- **aember's contract lives in `aember/contract.py`.** It must match aember's
  `services/containerd` (container-parser.cpp, container-manager.cpp,
  init-wrapper.h): the paths under `/var/lib/aember`, the containers.json
  keys, what containerd mounts (`/host-logs`, `/busybox.aember-init`, the
  `<rootfs>-lower/tmp` tmpfs → the image needs the `MOUNT_POINTS`). When
  aember changes any of that, change it here and in the tests together.
- lxc.container.conf: `lxc.rootfs.path = dir:/var/lib/aember/containers/<name>`
  (containerd mounts the overlay there before LXC starts), cgroup2 keys
  (`lxc.cgroup2.devices.allow`), device binds always `optional`.
  `lxc.console.logfile` (`console_log`) keeps the app's output; it only
  receives it with an aember whose init wrapper redirects the app to
  `/dev/console` (LXC gives a daemonized init `/dev/null`).
- Networks: `host` → `lxc.net.0.type = none` (shares aember's network
  namespace), `isolated` → `empty`, bridge → `veth` on an aember bridge
  (containers.json `"bridges"`; aember does no NAT there).
- The CLI is called `aember` and lives in `aember-cli/`, like in aember,
  aember-resources and aember-website; keep that name and layout. Its
  package is `aember` too, so never `pip install` it into aember's dev
  container venv (aember's own CLI is the `aember` package there); always
  run it through `run.py`. Loggers: `aember.<module>`.
- `project-cli/` is a **separate package** (`aember_project`) so it never
  collides with `aember-cli/`'s `aember` package; it packs by running
  `aember-cli/run.py` as a subprocess. The container repos import it from
  their `tools/aember-build-helper` submodule: a change to `Project` or
  `main` is an interface change for all of them (bump their submodules).
- Errors are `ManifestError` / `RuntimeError` with a message for the user;
  `cli.main` turns them into exit status 1. No tracebacks for user mistakes.
- Docker: always `--platform` from `PLATFORMS`; `docker create` gets a
  dummy command (never run) because images without CMD can't be created.

## Tests

- `python3 -m unittest discover -s aember-cli/tests -t aember-cli` and the
  same for `project-cli` (host or dev container). Add a test for every change; tests needing `mksquashfs`
  4.6+ or gcc use the skip decorators in `aember-cli/tests/helpers.py`.
- Before calling a change to the image layout, lxc config or containers.json
  entry done, run `tests/e2e/aember-qemu.sh /aember_ws/aember` in the aember
  dev container (docker CLI, SDK, QEMU). It modifies aember's x64 overlay
  temporarily and restores it (trap), then re-packs aember. It needs this
  repo inside the container's view: copy it under `/aember_ws/aember/build/`
  (git-ignored there) if the aember container doesn't mount it.
- The e2e checks the containers' output through aember's debug shell (`d`
  on the console, a command, `exit`), because aember's console log is muted
  while the shell is open.

- CI (`.github/workflows/ci.yml`): the unit tests on Python 3.10, 3.12 and
  3.13 with squashfs-tools 4.6 on every push and pull request; keep 3.10
  working (no newer syntax or stdlib APIs).

## Conventions

- black formatting, 88 columns, `from __future__ import annotations`,
  type hints, small functions; module docstrings say what and why.
- Keep README.md (user documentation, manifest reference table) and this
  file current in the same change.
- Commit, push and merge only when asked.
