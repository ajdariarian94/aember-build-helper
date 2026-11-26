import json
import os
import tempfile
import unittest
from pathlib import Path

from aember import aember_package
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
        package = bundle / "app.aember"
        self.assertFalse(aember_package.read_footer(package).signed)
        config = aember_package.extract(package, self.dir / "x")
        self.assertEqual(config["command"], ["/usr/bin/app"])
        self.assertIn(
            "lxc.environment = A=1", (self.dir / "x/lxc.container.conf").read_text()
        )
        self.assertTrue((self.dir / "x/image.squashfs").stat().st_size > 0)
        self.assertEqual(
            json.loads((bundle / "container.json").read_text()), {"name": "app"}
        )
        self.assertEqual(json.loads((bundle / "config.json").read_text()), config)

        overlay = self.dir / "resources" / "x64-poky-linux" / "rootfs"
        (overlay / "etc" / "aember").mkdir(parents=True)
        self.assertEqual(main(["install", str(self.dir)]), 0)
        self.assertTrue((overlay / "var/lib/aember/packages/app.aember").exists())
        cfg = json.loads((overlay / "etc/aember/containers.json").read_text())
        self.assertEqual(cfg["containers"], [{"name": "app"}])

    @needs_squashfs
    def test_build_signed(self):
        stage = self.dir / "stage"
        stage.mkdir()
        (stage / "app").write_text("x")
        Path("aember-container.json").write_text(
            json.dumps({"name": "app", "rootfs": {"dir": "stage"}, "command": ["/app"]})
        )
        private, public = aember_package.keygen(self.dir / "keys", "dev")
        self.assertEqual(main(["build", "--key", str(private)]), 0)
        package = self.dir / "aember-out" / "app" / "app.aember"
        keys = {"dev": aember_package.read_public_key(public)}
        self.assertEqual(aember_package.verify(package, keys), "dev")

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
        self.assertTrue((self.dir / "aember-out/x/x.aember").exists())

    def test_install_before_build_fails(self):
        Path("aember-container.json").write_text(
            json.dumps({"name": "app", "rootfs": {"dir": "s"}, "command": ["/a"]})
        )
        self.assertEqual(main(["install", str(self.dir)]), 1)


if __name__ == "__main__":
    unittest.main()
