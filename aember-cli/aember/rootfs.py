"""
The container's root file system as one tar stream, packed into SquashFS
by `mksquashfs - <out> -tar` (squashfs-tools 4.6+): no root needed, and
file owners and modes from a Docker image are kept.

    base     a Docker image (exported), a Dockerfile (built, exported) or a
             directory (owned by root in the image)
    + files  the manifest's "files", then the libraries they need (libs)
    + the directories aember mounts over (/proc, /tmp, /host-logs, ...)

A file given in "files" replaces the base's file of the same path.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tarfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator

from . import contract, libs
from .manifest import Manifest

log = logging.getLogger("aember.rootfs")


@dataclass
class ImageConfig:
    """What a Docker image says about how it runs."""

    command: list[str] | None = None
    env: dict[str, str] | None = None
    workdir: str | None = None


def _norm(name: str) -> str:
    """Tar member name → "usr/bin/x" (no leading "./" or "/", no trailing "/")."""
    while name.startswith("./"):
        name = name[2:]
    name = name.lstrip("/").rstrip("/")
    return "" if name == "." else name


def docker() -> str:
    tool = shutil.which("docker")
    if not tool:
        raise RuntimeError("docker not found: a Docker rootfs needs the Docker CLI")
    return tool


def build_dockerfile(m: Manifest) -> str:
    """docker build for the target platform; returns the image id."""
    iid = m.base / f".aember-build-{m.name}.iid"
    try:
        subprocess.run(
            [
                docker(),
                "build",
                "--platform",
                m.platform,
                "-f",
                str(m.dockerfile),
                "--iidfile",
                str(iid),
                str(m.context),
            ],
            check=True,
        )
        return iid.read_text().strip()
    finally:
        iid.unlink(missing_ok=True)


def image_config(image: str) -> ImageConfig:
    out = subprocess.run(
        [docker(), "image", "inspect", "--format", "{{json .Config}}", image],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    cfg = json.loads(out) or {}
    command = (cfg.get("Entrypoint") or []) + (cfg.get("Cmd") or [])
    env = dict(e.split("=", 1) for e in cfg.get("Env") or [] if "=" in e)
    return ImageConfig(command or None, env or None, cfg.get("WorkingDir") or None)


def ensure_image(image: str, platform: str) -> None:
    """Pull @p image for @p platform unless that platform is already local."""
    res = subprocess.run(
        [docker(), "image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", image],
        capture_output=True,
        text=True,
    )
    have = res.stdout.strip()
    if res.returncode == 0 and platform.startswith(have):
        return
    subprocess.run([docker(), "pull", "--platform", platform, image], check=True)


@contextmanager
def docker_export(image: str, platform: str) -> Iterator[BinaryIO]:
    """The file system of @p image as a tar stream (a stopped container)."""
    cid = subprocess.run(
        # The command is never run: some images have none, create needs one.
        [docker(), "create", "--platform", platform, image, "/aember-none"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    proc = subprocess.Popen([docker(), "export", cid], stdout=subprocess.PIPE)
    try:
        yield proc.stdout
    finally:
        proc.stdout.close()
        proc.wait()
        subprocess.run([docker(), "rm", "-f", cid], capture_output=True)
    if proc.returncode not in (0, None, -13):  # -13: we stopped reading
        raise RuntimeError(f"docker export {image} failed ({proc.returncode})")


def _dir_members(root: Path) -> Iterator[tuple[tarfile.TarInfo, Path | None]]:
    """A directory as root-owned tar members (sorted, reproducible)."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        here = Path(dirpath)
        for entry in [
            *(here / d for d in dirnames),
            *(here / f for f in sorted(filenames)),
        ]:
            rel = entry.relative_to(root).as_posix()
            info = tarfile.TarInfo(rel)
            st = entry.lstat()
            info.mode = st.st_mode & 0o7777
            info.mtime = int(st.st_mtime)
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            if entry.is_symlink():
                info.type = tarfile.SYMTYPE
                info.linkname = os.readlink(entry)
                yield info, None
            elif entry.is_dir():
                info.type = tarfile.DIRTYPE
                yield info, None
            elif entry.is_file():
                info.size = st.st_size
                yield info, entry
            # sockets, fifos, devices in a staging dir: skipped


def _file_member(
    name: str, src: Path, mode: int | None
) -> tuple[tarfile.TarInfo, Path]:
    real = src.resolve()
    st = real.stat()
    info = tarfile.TarInfo(name.lstrip("/"))
    info.size = st.st_size
    info.mode = mode if mode is not None else st.st_mode & 0o7777
    info.mtime = int(st.st_mtime)
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    return info, real


def _dir_member(name: str, mode: int = 0o755) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = mode
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    return info


def additions(m: Manifest) -> dict[str, tuple[tarfile.TarInfo, Path]]:
    """The manifest's files and the libraries they (and a dir rootfs) need."""
    out: dict[str, tuple[tarfile.TarInfo, Path]] = {}
    for f in m.files:
        if not f.src.is_file():
            raise RuntimeError(f"files: {f.src} not found")
        out[_norm(f.dst)] = _file_member(f.dst, f.src, f.mode)
    if m.sysroot:
        if not m.sysroot.is_dir():
            raise RuntimeError(f"libs: sysroot {m.sysroot} not found")
        elves = [p for _info, p in out.values() if libs.is_elf(p)]
        if m.dir:
            elves += [
                p
                for _info, p in _dir_members(m.dir)
                if p is not None and libs.is_elf(p)
            ]
        for dst, src in sorted(libs.resolve(elves, m.sysroot).items()):
            key = _norm(dst)
            if key not in out and not (m.dir and (m.dir / key).exists()):
                out[key] = _file_member(dst, src, None)
    return out


def write_stream(m: Manifest, sink: BinaryIO) -> ImageConfig:
    """Write the whole root file system as a tar stream to @p sink."""
    extra = additions(m)
    config = ImageConfig()
    seen: set[str] = set()
    with tarfile.open(fileobj=sink, mode="w|", format=tarfile.PAX_FORMAT) as out:

        def add_base(info: tarfile.TarInfo, fobj) -> None:
            key = _norm(info.name)
            if not key or key in extra:
                return  # the root itself; or replaced by a manifest file
            seen.add(key)
            out.addfile(info, fobj)

        if m.source in ("docker_image", "dockerfile"):
            if m.source == "dockerfile":
                image = build_dockerfile(m)
            else:
                image = m.docker_image
                ensure_image(image, m.platform)
            config = image_config(image)
            with docker_export(image, m.platform) as stream:
                with tarfile.open(fileobj=stream, mode="r|") as base:
                    for info in base:
                        fobj = base.extractfile(info) if info.isreg() else None
                        add_base(info, fobj)
        else:
            if not m.dir or not m.dir.is_dir():
                raise RuntimeError(f"rootfs.dir {m.dir} not found")
            for info, path in _dir_members(m.dir):
                if path is None:
                    add_base(info, None)
                else:
                    with path.open("rb") as f:
                        add_base(info, f)

        def ensure_parents(key: str) -> None:
            parts = key.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                parent = "/".join(parts[:i])
                if parent not in seen:
                    seen.add(parent)
                    out.addfile(_dir_member(parent))

        for key, mode in contract.MOUNT_POINTS.items():
            if key not in seen:
                seen.add(key)
                out.addfile(_dir_member(key, mode))
        for key, (info, path) in sorted(extra.items()):
            ensure_parents(key)
            with path.open("rb") as f:
                out.addfile(info, f)
            seen.add(key)
    return config


def mksquashfs() -> str:
    tool = shutil.which("mksquashfs")
    if not tool:
        raise RuntimeError("mksquashfs not found (squashfs-tools 4.6+)")
    out = subprocess.run([tool, "-version"], capture_output=True, text=True).stdout
    try:
        major, minor = (int(x) for x in out.split()[2].split(".")[:2])
    except (IndexError, ValueError):
        return tool
    if (major, minor) < (4, 6):
        raise RuntimeError(f"mksquashfs {major}.{minor}: 4.6 or newer is needed (-tar)")
    return tool


def build_squashfs(m: Manifest, out: Path) -> ImageConfig:
    """Pack the root file system into @p out; returns the image's config."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    proc = subprocess.Popen(
        [
            mksquashfs(),
            "-",
            str(out),
            "-tar",
            "-comp",
            m.compression,
            "-noappend",
            "-no-progress",
            "-quiet",
        ],
        stdin=subprocess.PIPE,
    )
    try:
        config = write_stream(m, proc.stdin)
    except BaseException:
        proc.kill()
        proc.wait()
        out.unlink(missing_ok=True)
        raise
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"mksquashfs failed ({proc.returncode})")
    return config


def list_squashfs(path: Path) -> list[str]:
    """The paths in a SquashFS image (for checks and tests)."""
    out = subprocess.run(
        ["unsquashfs", "-lls", "-d", "", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line[:1] in "-dlcbps"]
