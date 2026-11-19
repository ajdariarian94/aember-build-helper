import io
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from aember_build_helper.manifest import parse
from aember_build_helper.rootfs import (
    _norm,
    build_squashfs,
    list_squashfs,
    write_stream,
)

from .helpers import needs_squashfs


def project(t: Path) -> Path:
    stage = t / "stage"
    (stage / "usr" / "bin").mkdir(parents=True)
    (stage / "usr" / "bin" / "app").write_text("#!/bin/sh\necho base\n")
    os.chmod(stage / "usr" / "bin" / "app", 0o755)
    (stage / "etc").mkdir()
    (stage / "etc" / "app.conf").write_text("x=1\n")
    os.symlink("app", stage / "usr" / "bin" / "app-link")
    (t / "override").write_text("#!/bin/sh\necho override\n")
    (t / "data.txt").write_text("data\n")
    return stage


def manifest(t: Path):
    project(t)
    return parse(
        {
            "name": "app",
            "rootfs": {"dir": "stage"},
            "command": ["/usr/bin/app"],
            "files": [
                {"src": "override", "dst": "/usr/bin/app", "mode": "0755"},
                {"src": "data.txt", "dst": "/opt/app/share/data.txt"},
            ],
        },
        t,
    )


class StreamTest(unittest.TestCase):
    def test_norm(self):
        self.assertEqual(_norm("./usr/bin/"), "usr/bin")
        self.assertEqual(_norm("/.hidden"), ".hidden")
        self.assertEqual(_norm("."), "")
        self.assertEqual(_norm("./"), "")

    def test_dir_rootfs_with_files_mount_points_and_root_owner(self):
        with tempfile.TemporaryDirectory() as t:
            buf = io.BytesIO()
            write_stream(manifest(Path(t)), buf)
            buf.seek(0)
            with tarfile.open(fileobj=buf) as tar:
                members = {m.name: m for m in tar.getmembers()}
                names = list(members)
                # replaced, not duplicated
                self.assertEqual(names.count("usr/bin/app"), 1)
                self.assertIn(b"override", tar.extractfile("usr/bin/app").read())
                self.assertEqual(members["usr/bin/app"].mode, 0o755)
                self.assertTrue(members["usr/bin/app-link"].issym())
                # parents of added files
                for d in ("opt", "opt/app", "opt/app/share"):
                    self.assertTrue(members[d].isdir(), d)
                # what aember mounts over
                for d in ("proc", "sys", "dev", "tmp", "run", "host-logs"):
                    self.assertTrue(members[d].isdir(), d)
                self.assertEqual(members["tmp"].mode, 0o1777)
                self.assertTrue(
                    all(m.uid == 0 and m.gid == 0 for m in members.values())
                )

    @needs_squashfs
    def test_squashfs_image(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "out" / "app.squashfs"
            build_squashfs(manifest(Path(t)), out)
            listing = "\n".join(list_squashfs(out))
            self.assertIn("/usr/bin/app", listing)
            self.assertIn("/host-logs", listing)
            self.assertIn("root/root", listing)
            dest = Path(t) / "x"
            subprocess.run(
                ["unsquashfs", "-q", "-n", "-d", str(dest), str(out)], check=True
            )
            self.assertIn("override", (dest / "usr/bin/app").read_text())


if __name__ == "__main__":
    unittest.main()
