"""
Shared libraries for ELF files from a sysroot (e.g. the aember SDK's
target sysroot): the program interpreter and every NEEDED library,
recursively, found the way the dynamic loader would in the sysroot's
standard directories (and Debian multiarch ones). readelf reads any architecture.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

SEARCH = ("lib", "lib64", "usr/lib", "usr/lib64", "usr/local/lib")
_NEEDED = re.compile(r"\(NEEDED\)\s+Shared library: \[(.+?)\]")
_INTERP = re.compile(r"\[Requesting program interpreter: (.+?)\]")


def is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
        return False


def readelf() -> str:
    tool = shutil.which("readelf")
    if not tool:
        raise RuntimeError("readelf not found (binutils): needed for 'libs'")
    return tool


def needed(path: Path) -> tuple[list[str], str | None]:
    """(NEEDED sonames, interpreter path) of an ELF file."""
    out = subprocess.run(
        [readelf(), "-d", "-l", "-W", str(path)],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    interp = _INTERP.search(out)
    return _NEEDED.findall(out), interp.group(1) if interp else None


def search_dirs(sysroot: Path) -> list[str]:
    """The standard directories, plus Debian-style multiarch ones."""
    multiarch = sorted(
        str(p.relative_to(sysroot))
        for base in ("lib", "usr/lib")
        for p in (sysroot / base).glob("*-linux-gnu*")
        if p.is_dir()
    )
    return [*SEARCH, *multiarch]


def find(sysroot: Path, soname: str, extra: list[str] | None = None) -> Path | None:
    for d in (*search_dirs(sysroot), *(extra or [])):
        cand = sysroot / d / soname
        if cand.exists():
            return cand
    return None


def resolve(elves: list[Path], sysroot: Path) -> dict[str, Path]:
    """
    Container path → file in the sysroot, for everything @p elves need.
    Raises RuntimeError listing the libraries the sysroot doesn't have.
    """
    result: dict[str, Path] = {}
    missing: set[str] = set()
    todo = list(elves)
    seen: set[Path] = set()
    while todo:
        elf = todo.pop()
        if elf in seen:
            continue
        seen.add(elf)
        sonames, interp = needed(elf)
        if interp:
            src = sysroot / interp.lstrip("/")
            if src.exists():
                result.setdefault(interp, src)
                todo.append(src.resolve())
            else:
                missing.add(interp)
        for soname in sonames:
            src = find(sysroot, soname)
            if src is None:
                missing.add(soname)
                continue
            dst = "/" + str(src.relative_to(sysroot))
            if dst not in result:
                result[dst] = src
                todo.append(src.resolve())
    if missing:
        raise RuntimeError(
            f"not in the sysroot {sysroot}: {', '.join(sorted(missing))}"
        )
    return result
