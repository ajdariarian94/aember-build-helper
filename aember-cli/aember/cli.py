"""
aember (aember-build-helper): pack your project into an aember-ready LXC container.

    aember init                 write an example aember-container.json
    aember check                validate the manifest
    aember build                build the container into aember-out/<name>/
    aember install <aember>     add it to an aember board's rootfs overlay

Python 3.10+ standard library only; needs mksquashfs (squashfs-tools 4.6+),
plus docker for Docker rootfs sources and readelf for "libs".
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__, contract
from .install import install, overlay_dir
from .manifest import EXAMPLE, PLATFORMS, Manifest, ManifestError, load
from .rootfs import build_squashfs

log = logging.getLogger("aember.cli")
DEFAULT_MANIFEST = "aember-container.json"
DEFAULT_OUT = "aember-out"


def build(m: Manifest, out_root: Path) -> Path:
    """Build the bundle out_root/<name>/; returns its directory."""
    bundle = out_root / m.name
    image_dir = bundle / "overlay" / contract.image_dir(m.name).lstrip("/")
    log.info("Packing %s for %s (%s rootfs)", m.name, m.arch, m.source)
    config = build_squashfs(m, image_dir / f"{m.name}.squashfs")

    # A Docker image's own settings fill what the manifest leaves out.
    command = m.command or config.command
    if not command:
        raise ManifestError("no 'command' and the Docker image has none")
    if config.env:
        m.env = {**config.env, **m.env}
    if config.workdir and not m.workdir:
        m.workdir = config.workdir

    (image_dir / "lxc.container.conf").write_text(contract.lxc_config(m))
    entry = contract.containers_entry(m, command)
    (bundle / "container.json").write_text(json.dumps(entry, indent=2) + "\n")
    size = (image_dir / f"{m.name}.squashfs").stat().st_size
    log.info("Built %s (%.1f MB): %s", m.name, size / 2**20, bundle)
    return bundle


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aember", description=__doc__.split("\n\n")[0])
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def manifest_args(p):
        p.add_argument("-m", "--manifest", type=Path, default=Path(DEFAULT_MANIFEST))
        p.add_argument("-a", "--arch", choices=list(PLATFORMS), help="Override 'arch'")

    p_init = sub.add_parser("init", help="Write an example manifest")
    p_init.add_argument("-m", "--manifest", type=Path, default=Path(DEFAULT_MANIFEST))
    p_init.add_argument("--name", default="hello")

    p_check = sub.add_parser("check", help="Validate the manifest")
    manifest_args(p_check)

    p_build = sub.add_parser("build", help="Build the container")
    manifest_args(p_build)
    p_build.add_argument("-o", "--out", type=Path, default=Path(DEFAULT_OUT))
    p_build.add_argument(
        "--rootfs-dir", type=Path, help="Use this directory as the rootfs (CMake)"
    )

    p_inst = sub.add_parser("install", help="Add a built container to aember")
    manifest_args(p_inst)
    p_inst.add_argument("target", type=Path, help="aember checkout or rootfs overlay")
    p_inst.add_argument("-o", "--out", type=Path, default=Path(DEFAULT_OUT))

    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="aember: %(message)s",
    )
    try:
        if args.cmd == "init":
            if args.manifest.exists():
                raise ManifestError(f"{args.manifest} exists already")
            data = {**EXAMPLE, "name": args.name}
            args.manifest.write_text(json.dumps(data, indent=2) + "\n")
            log.info("Wrote %s: edit it, then run aember build", args.manifest)
            return 0

        m = load(args.manifest, args.arch)
        if args.cmd == "check":
            log.info(
                "%s: OK (%s, %s, %s rootfs)", args.manifest, m.name, m.arch, m.source
            )
        elif args.cmd == "build":
            if args.rootfs_dir:
                m.source, m.dir = "dir", args.rootfs_dir.resolve()
                m.docker_image = m.dockerfile = None
                if not m.command:
                    raise ManifestError("--rootfs-dir needs 'command' in the manifest")
            build(m, args.out)
        elif args.cmd == "install":
            bundle = args.out / m.name
            if not (bundle / "container.json").exists():
                raise ManifestError(f"{bundle}: not built yet (aember build)")
            overlay = overlay_dir(args.target, m.arch)
            for w in install(bundle, overlay):
                log.warning("warning: %s", w)
            log.info(
                "Installed %s into %s. In aember: aember app pack, then launch "
                "(or build a board image).",
                m.name,
                overlay,
            )
    except (ManifestError, RuntimeError) as e:
        log.error("error: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
