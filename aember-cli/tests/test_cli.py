import json
import os
import tempfile
import unittest
from pathlib import Path

from aember.cli import main

from .helpers import needs_squashfs


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.old = os.getcwd()
        os.chdir(self.dir)

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def test_init_then_check(self):
        self.assertEqual(main(["init", "--name", "demo"]), 0)
        data = json.loads(Path("aember-container.json").read_text())
        self.assertEqual(data["name"], "demo")
        self.assertEqual(main(["check"]), 0)
        self.assertEqual(main(["init"]), 1)  # never overwrites

    def test_check_fails_on_a_bad_manifest(self):
        Path("aember-container.json").write_text('{"name": "X"}')
        self.assertEqual(main(["check"]), 1)

    @needs_squashfs
    def test_build_and_install(self):
        stage = self.dir / "stage" / "usr" / "bin"
        stage.mkdir(parents=True)
        (stage / "app").write_text("#!/bin/sh\n")
        Path("aember-container.json").write_text(
            json.dumps(
                {
                    "name": "app",
                    "rootfs": {"dir": "stage"},
                    "command": ["/usr/bin/app"],
                    "env": {"A": "1"},
                }
            )
        )
        self.assertEqual(main(["build"]), 0)
        bundle = self.dir / "aember-out" / "app"
        img = bundle / "overlay/var/lib/aember/app"
        self.assertTrue((img / "app.squashfs").stat().st_size > 0)
        self.assertIn("lxc.environment = A=1", (img / "lxc.container.conf").read_text())
        entry = json.loads((bundle / "container.json").read_text())
        self.assertEqual(entry["container"]["args"], ["/usr/bin/app"])

        overlay = self.dir / "resources" / "x64-poky-linux" / "rootfs"
        (overlay / "etc" / "aember").mkdir(parents=True)
        self.assertEqual(main(["install", str(self.dir)]), 0)
        self.assertTrue((overlay / "var/lib/aember/app/app.squashfs").exists())
        cfg = json.loads((overlay / "etc/aember/containers.json").read_text())
        self.assertEqual(cfg["containers"][0]["name"], "app")

    @needs_squashfs
    def test_rootfs_dir_override_for_cmake(self):
        other = self.dir / "staging"
        (other / "bin").mkdir(parents=True)
        (other / "bin" / "x").write_text("x")
        Path("aember-container.json").write_text(
            json.dumps(
                {
                    "name": "x",
                    "rootfs": {"docker_image": "unused"},
                    "command": ["/bin/x"],
                }
            )
        )
        self.assertEqual(
            main(["build", "--rootfs-dir", str(other), "-a", "arm-poky-linux"]), 0
        )
        self.assertTrue(
            (self.dir / "aember-out/x/overlay/var/lib/aember/x/x.squashfs").exists()
        )

    def test_install_before_build_fails(self):
        Path("aember-container.json").write_text(
            json.dumps({"name": "app", "rootfs": {"dir": "s"}, "command": ["/a"]})
        )
        self.assertEqual(main(["install", str(self.dir)]), 1)


if __name__ == "__main__":
    unittest.main()
