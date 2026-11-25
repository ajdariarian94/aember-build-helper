"""Builds: cross builds with an SDK (`build`), the unit tests (`test`: host
compiler or x64 SDK), and packing the staged install as an aember container
(`pack`, `install`) with aember-build-helper's own `aember` CLI."""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import sys
from pathlib import Path

from aember_project import sdk
from aember_project.project import Project

log = logging.getLogger("aember.build")

# aember-build-helper's packing CLI: this package lives in the same checkout.
BUILD_HELPER = Path(__file__).resolve().parents[2] / "aember-cli" / "run.py"


def jobs() -> int:
    """2/3 of the CPUs (all of them crashes WSL), or $AEMBER_BUILD_JOBS."""
    env = os.environ.get("AEMBER_BUILD_JOBS")
    if env:
        return max(1, int(env))
    return max(1, (os.cpu_count() or 3) * 2 // 3)


def build_dir(root: Path, arch: str, build_type: str) -> Path:
    return root / "build" / "configure" / arch / build_type


def stage_dir(root: Path, arch: str) -> Path:
    return root / "build" / "stage" / arch


def out_dir(root: Path, arch: str) -> Path:
    return root / "build" / "aember-out" / arch


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    log.debug("$ %s", shlex.join(cmd))
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def run_in_sdk(root: Path, arch: str, commands: list[str]) -> None:
    """Run shell @p commands (joined with &&) in @p arch's SDK environment."""
    line = sdk.shell(root, arch, " && ".join(commands))
    log.debug("$ %s", line)
    subprocess.run(["bash", "-c", line], cwd=root, check=True)


TOOLCHAIN = "$OECORE_NATIVE_SYSROOT/usr/share/cmake/OEToolchainConfig.cmake"


def configure(root: Path, bdir: Path, build_type: str, tests: bool) -> list[str]:
    return [
        "cmake",
        "-S",
        str(root),
        "-B",
        str(bdir),
        "-G",
        "Ninja",
        f"-DCMAKE_BUILD_TYPE={build_type}",
        f"-DBUILD_TESTS={'ON' if tests else 'OFF'}",
    ]


def in_sdk(cmd: list[str]) -> str:
    """@p cmd for an SDK shell, with the SDK's CMake toolchain file (its
    path is an SDK variable, so it stays unquoted)."""
    return f'{shlex.join(cmd)} "-DCMAKE_TOOLCHAIN_FILE={TOOLCHAIN}"'


def build_cmd(bdir: Path) -> str:
    return f"cmake --build {shlex.quote(str(bdir))} --parallel {jobs()}"


def cross_build(project: Project, arch: str, build_type: str = "Release") -> Path:
    """Configure, build and install into build/stage/<arch>/ with the SDK."""
    root = project.root
    bdir = build_dir(root, arch, build_type)
    stage = shlex.quote(str(stage_dir(root, arch)))
    run_in_sdk(
        root,
        arch,
        [
            in_sdk(configure(root, bdir, build_type, tests=False)),
            build_cmd(bdir),
            f"rm -rf {stage}",
            f"cmake --install {shlex.quote(str(bdir))} --prefix {stage}",
        ],
    )
    log.info("Installed %s for %s into %s", project.name, arch, stage_dir(root, arch))
    return stage_dir(root, arch)


SANITIZE_FLAGS = "-fsanitize=address,undefined -fno-omit-frame-pointer"
SANITIZER_ENV = {
    "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
    "UBSAN_OPTIONS": "print_stacktrace=1:halt_on_error=1",
}


def host_test_dir(root: Path, sanitize: bool = False) -> Path:
    return build_dir(root, "host", "Debug-asan" if sanitize else "Debug")


def host_tests(root: Path, sanitize: bool = False) -> None:
    """Build the unit tests with the host compiler and run them with ctest
    (@p sanitize: ASan + UBSan)."""
    bdir = host_test_dir(root, sanitize)
    flags = {"CXXFLAGS": SANITIZE_FLAGS, "LDFLAGS": SANITIZE_FLAGS} if sanitize else {}
    run(configure(root, bdir, "Debug", tests=True), root, {**os.environ, **flags})
    run(["cmake", "--build", str(bdir), "--parallel", str(jobs())], root)
    run(
        ["ctest", "--test-dir", str(bdir), "--output-on-failure"],
        root,
        {**os.environ, **(SANITIZER_ENV if sanitize else {})},
    )


TEST_ARCH = "x64-poky-linux"
# glibc's loader in the x64 SDK sysroot (runs the SDK's binaries on the host)
TEST_LOADER = "ld-linux-x86-64.so.2"


def sdk_test_dir(root: Path, sanitize: bool = False) -> Path:
    return build_dir(root, TEST_ARCH, "Debug-tests-asan" if sanitize else "Debug-tests")


def sdk_test_commands(
    root: Path, bdir: Path, sanitize: bool = False
) -> tuple[list[list[str]], dict[str, str]]:
    """Each `*-unittest` in @p bdir as a command through the SDK's loader,
    and the environment they run in (the sysroot's Qt plugins, offscreen)."""
    sysroot = sdk.sysroot(root, TEST_ARCH)
    libs = ":".join(str(sysroot / d) for d in ("lib", "usr/lib"))
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "QT_PLUGIN_PATH": str(sysroot / "usr" / "lib" / "plugins"),
        **(SANITIZER_ENV if sanitize else {}),
    }
    env.pop("LD_LIBRARY_PATH", None)
    tests = sorted(p for p in bdir.rglob("*-unittest") if p.is_file())
    if not tests:
        raise FileNotFoundError(f"No test binaries in {bdir}")
    loader = str(sysroot / "lib" / TEST_LOADER)
    return [[loader, "--library-path", libs, str(t)] for t in tests], env


def sdk_tests(root: Path, sanitize: bool = False) -> None:
    """Build the unit tests with the x64 SDK and run each `*-unittest`
    through the SDK's loader, with the sysroot's libraries and Qt plugins
    (offscreen). @p sanitize: ASan + UBSan (the SDK's gcc-sanitizers)."""
    bdir = sdk_test_dir(root, sanitize)
    # The SDK's environment-setup sets CXXFLAGS/LDFLAGS: append to them.
    san = [
        f'export CXXFLAGS="$CXXFLAGS {SANITIZE_FLAGS}" '
        f'LDFLAGS="$LDFLAGS {SANITIZE_FLAGS}"'
    ]
    run_in_sdk(
        root,
        TEST_ARCH,
        (san if sanitize else [])
        + [in_sdk(configure(root, bdir, "Debug", tests=True)), build_cmd(bdir)],
    )
    commands, env = sdk_test_commands(root, bdir, sanitize)
    for cmd in commands:
        log.info("Running %s", Path(cmd[-1]).name)
        run(cmd, root, env)


def container_manifest(project: Project, arch: str) -> Path:
    """aember-container.json for @p arch: the repo's manifest plus the arch
    and the SDK sysroot the libraries come from."""
    root = project.root
    manifest = json.loads((root / "aember-container.json").read_text())
    if manifest.get("name") != project.name:
        raise ValueError(
            f"aember-container.json names {manifest.get('name')!r}, "
            f"the CLI {project.name!r}"
        )
    manifest["arch"] = arch
    manifest["rootfs"] = {"dir": str(stage_dir(root, arch))}
    manifest.setdefault("libs", {})["sysroot"] = str(sdk.sysroot(root, arch))
    files = []
    for f in manifest.get("files", []):
        # "{sysroot}/..." is a file from the SDK's target sysroot; other paths
        # are relative to the repo. "optional": skip it if the arch lacks it
        # (e.g. glibc's locale archive on musl).
        src = f["src"].replace("{sysroot}", str(sdk.sysroot(root, arch)))
        src_path = (root / src).resolve()
        if f.pop("optional", False) and not src_path.exists():
            log.info("%s: no %s, skipped", arch, src)
            continue
        f["src"] = str(src_path)
        files.append(f)
    if "files" in manifest:
        manifest["files"] = files
    path = root / "build" / "manifests" / arch / "aember-container.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path


def pack(project: Project, arch: str) -> Path:
    """Pack build/stage/<arch>/ into build/aember-out/<arch>/<name>/."""
    root = project.root
    if not stage_dir(root, arch).is_dir():
        raise FileNotFoundError(
            f"Nothing staged for {arch}: run `aember build -a {arch}`"
        )
    out = out_dir(root, arch)
    run(
        [
            sys.executable,
            str(BUILD_HELPER),
            "build",
            "--manifest",
            str(container_manifest(project, arch)),
            "--out",
            str(out),
        ],
        root,
    )
    return out / project.name


def install(project: Project, arch: str, target: Path) -> None:
    """Put the packed container into an aember checkout's overlay."""
    root = project.root
    run(
        [
            sys.executable,
            str(BUILD_HELPER),
            "install",
            str(target),
            "--manifest",
            str(container_manifest(project, arch)),
            "--arch",
            arch,
            "--out",
            str(out_dir(root, arch)),
        ],
        root,
    )
