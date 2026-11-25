"""`aember`: the command line of a container repository (its
aember-cli/run.py calls `main` with the repository's `Project`).

    aember sdk -a <arch>        fetch and install the aember-resources SDK
    aember build -a <arch>      cross-build and stage the install
    aember pack -a <arch>       pack the staged install as an aember container
    aember install -a <arch> <aember checkout>
    aember test                 the C++ unit tests (host compiler or x64 SDK)
    aember mutate [-n N]        mutation testing of those unit tests
    aember all -a <arch>        sdk + build + pack
"""

from __future__ import annotations

import argparse
import logging
import subprocess
from pathlib import Path

from aember_project import build, mutate, sdk
from aember_project.project import Project

log = logging.getLogger("aember")


def main(project: Project, argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aember", description=f"{project.name} tools")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)

    def arch_arg(p: argparse.ArgumentParser) -> None:
        p.add_argument("-a", "--arch", default="x64-poky-linux", choices=sdk.ARCHS)

    p = sub.add_parser("sdk", help="fetch and install an SDK")
    arch_arg(p)
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("build", help="cross-build and stage")
    arch_arg(p)
    p.add_argument("--build-type", default="Release", choices=["Release", "Debug"])
    p = sub.add_parser("pack", help="pack the staged install as a container")
    arch_arg(p)
    p = sub.add_parser("install", help="install the container into aember")
    arch_arg(p)
    p.add_argument("target", type=Path, help="aember checkout or rootfs overlay")
    p = sub.add_parser("all", help="sdk + build + pack")
    arch_arg(p)
    p = sub.add_parser("test", help="unit tests")
    p.add_argument(
        "--sanitize", action="store_true", help="C++ tests with ASan + UBSan"
    )
    p = sub.add_parser("mutate", help="mutation testing of the unit tests")
    p.add_argument("-n", "--max", type=int, default=0, help="a sample (0: all)")
    p.add_argument("--seed", type=int, default=1, help="same seed, same sample")
    p.add_argument("--timeout", type=float, default=120, help="seconds per suite")
    p.add_argument(
        "-f", "--file", action="append", help="only sources whose path has this"
    )

    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        if args.command == "sdk":
            sdk.fetch(project, args.arch, force=args.force)
        elif args.command == "build":
            build.cross_build(project, args.arch, args.build_type)
        elif args.command == "pack":
            log.info("Packed %s", build.pack(project, args.arch))
        elif args.command == "install":
            build.install(project, args.arch, args.target)
        elif args.command == "all":
            sdk.fetch(project, args.arch)
            build.cross_build(project, args.arch)
            log.info("Packed %s", build.pack(project, args.arch))
        elif args.command == "test":
            tests = build.sdk_tests if project.tests == "sdk" else build.host_tests
            tests(project.root, sanitize=args.sanitize)
        elif args.command == "mutate":
            mutate.mutate(project, args.max, args.seed, args.timeout, args.file)
    except (FileNotFoundError, ValueError) as e:
        log.error("%s", e)
        return 1
    except subprocess.CalledProcessError as e:
        log.error("command failed (exit %s): %s", e.returncode, e.cmd)
        return 1
    return 0
