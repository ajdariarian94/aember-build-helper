"""
The container manifest (aember-container.json, next to the project).

Paths in it are relative to the manifest's directory. Only `name` and one
rootfs source are required; everything else has aember's defaults.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# aember architecture → Docker platform.
PLATFORMS = {
    "x64-poky-linux": "linux/amd64",
    "aarch64-poky-linux": "linux/arm64",
    "arm-poky-linux": "linux/arm/v7",
}
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
RESTART_POLICIES = ("no", "on-failure", "always")
NETWORKS = ("host", "isolated")
COMPRESSIONS = ("xz", "zstd", "gzip")
SOURCES = ("docker_image", "dockerfile", "dir")


class ManifestError(ValueError):
    pass


@dataclass
class FileSpec:
    src: Path
    dst: str  # absolute path inside the container
    mode: int | None = None


@dataclass
class Bridge:
    name: str
    address: str  # the container's address, CIDR
    gateway: str | None = None


@dataclass
class Manifest:
    name: str
    base: Path  # the manifest's directory
    arch: str = "x64-poky-linux"
    source: str = "dir"  # one of SOURCES
    docker_image: str | None = None
    dockerfile: Path | None = None
    context: Path | None = None
    dir: Path | None = None
    files: list[FileSpec] = field(default_factory=list)
    sysroot: Path | None = None  # copy the libraries ELF files need from here
    command: list[str] | None = None  # None: the Docker image's entrypoint + cmd
    env: dict[str, str] = field(default_factory=dict)
    workdir: str | None = None
    network: str | Bridge = "host"
    devices: list[str] = field(default_factory=list)
    device_allow: list[str] = field(default_factory=list)
    lxc: list[str] = field(default_factory=list)
    restart_policy: str = "always"
    max_restart_attempts: int = 5
    restart_delay: int = 5
    stop_timeout: int = 10
    init: bool = True
    dependencies: list[str] = field(default_factory=list)
    compression: str = "xz"
    console_log: bool = True

    @property
    def platform(self) -> str:
        return PLATFORMS[self.arch]


def _abs(base: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (base / p)


def parse(data: dict, base: Path, arch: str | None = None) -> Manifest:
    """Validate @p data (the JSON object); raise ManifestError on problems."""
    if not isinstance(data, dict):
        raise ManifestError("the manifest must be a JSON object")
    known = {
        "name", "arch", "rootfs", "files", "libs", "command", "env", "workdir",
        "network", "devices", "device_allow", "lxc", "restart_policy",
        "max_restart_attempts", "restart_delay", "stop_timeout", "init",
        "dependencies", "compression", "console_log", "$schema", "description",
    }  # fmt: skip
    unknown = sorted(set(data) - known)
    if unknown:
        raise ManifestError(f"unknown keys: {', '.join(unknown)}")

    name = data.get("name")
    if not isinstance(name, str) or not NAME.match(name):
        raise ManifestError(
            "'name' must be lowercase letters, digits and '-' (it becomes a "
            "directory, the LXC name and the hostname)"
        )
    m = Manifest(name=name, base=base)

    m.arch = arch or data.get("arch", m.arch)
    if m.arch not in PLATFORMS:
        raise ManifestError(f"'arch' must be one of {', '.join(PLATFORMS)}")

    rootfs = data.get("rootfs")
    if not isinstance(rootfs, dict):
        raise ManifestError(f"'rootfs' must be an object with one of {SOURCES}")
    given = [k for k in SOURCES if k in rootfs]
    if len(given) != 1:
        raise ManifestError(f"'rootfs' needs exactly one of {', '.join(SOURCES)}")
    m.source = given[0]
    if m.source == "docker_image":
        m.docker_image = str(rootfs["docker_image"])
    elif m.source == "dockerfile":
        m.dockerfile = _abs(base, rootfs["dockerfile"])
        m.context = _abs(base, rootfs.get("context", "."))
    else:
        m.dir = _abs(base, rootfs["dir"])

    for i, f in enumerate(data.get("files", [])):
        if not isinstance(f, dict) or "src" not in f or "dst" not in f:
            raise ManifestError(f"files[{i}] needs 'src' and 'dst'")
        if not str(f["dst"]).startswith("/"):
            raise ManifestError(f"files[{i}].dst must be an absolute path")
        mode = f.get("mode")
        m.files.append(
            FileSpec(
                _abs(base, f["src"]),
                str(f["dst"]),
                int(mode, 8) if isinstance(mode, str) else mode,
            )
        )

    libs = data.get("libs")
    if libs is not None:
        if not isinstance(libs, dict) or "sysroot" not in libs:
            raise ManifestError('\'libs\' must be {"sysroot": "<dir>"}')
        m.sysroot = _abs(base, libs["sysroot"])

    cmd = data.get("command")
    if cmd is not None:
        if not (isinstance(cmd, list) and cmd and all(isinstance(c, str) for c in cmd)):
            raise ManifestError("'command' must be a non-empty list of strings")
        m.command = cmd
    elif m.source != "docker_image" and m.source != "dockerfile":
        raise ManifestError("'command' is required (only Docker images have one)")

    env = data.get("env", {})
    if not isinstance(env, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in env.items()
    ):
        raise ManifestError("'env' must map strings to strings")
    m.env = dict(env)
    m.workdir = data.get("workdir")

    net = data.get("network", "host")
    if isinstance(net, dict):
        if "bridge" not in net or "address" not in net:
            raise ManifestError("a bridge network needs 'bridge' and 'address'")
        m.network = Bridge(net["bridge"], net["address"], net.get("gateway"))
    elif net in NETWORKS:
        m.network = net
    else:
        raise ManifestError(
            '\'network\' must be "host", "isolated" or '
            '{"bridge": ..., "address": ...}'
        )

    for key in ("devices", "device_allow", "lxc", "dependencies"):
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ManifestError(f"'{key}' must be a list of strings")
        setattr(m, key, list(value))

    m.restart_policy = data.get("restart_policy", m.restart_policy)
    if m.restart_policy not in RESTART_POLICIES:
        raise ManifestError(f"'restart_policy' must be one of {RESTART_POLICIES}")
    for key in ("max_restart_attempts", "restart_delay", "stop_timeout"):
        value = data.get(key, getattr(m, key))
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ManifestError(f"'{key}' must be a whole number >= 0")
        setattr(m, key, value)
    init = data.get("init", True)
    if not isinstance(init, bool):
        raise ManifestError("'init' must be true or false")
    m.init = init
    console_log = data.get("console_log", True)
    if not isinstance(console_log, bool):
        raise ManifestError("'console_log' must be true or false")
    m.console_log = console_log
    m.compression = data.get("compression", m.compression)
    if m.compression not in COMPRESSIONS:
        raise ManifestError(f"'compression' must be one of {COMPRESSIONS}")
    return m


def load(path: Path, arch: str | None = None) -> Manifest:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        raise ManifestError(f"{path}: not found (aember init writes one)") from None
    except json.JSONDecodeError as e:
        raise ManifestError(f"{path}: invalid JSON: {e}") from None
    return parse(data, path.resolve().parent, arch)


EXAMPLE = {
    "name": "hello",
    "arch": "x64-poky-linux",
    "rootfs": {"dockerfile": "Dockerfile", "context": "."},
    "command": ["/usr/local/bin/hello"],
    "env": {"HELLO": "aember"},
    "network": "host",
    "restart_policy": "always",
    "max_restart_attempts": 5,
    "restart_delay": 5,
    "stop_timeout": 10,
}
