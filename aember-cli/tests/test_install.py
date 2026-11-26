import json
import tempfile
import unittest
from pathlib import Path

from aember import aember_package
from aember.install import install, merge_entry, overlay_dir

SEED = bytes(range(32))


def bundle(root: Path, name="app", link=None, seed=None, deps=None) -> Path:
    b = root / "aember-out" / name
    b.mkdir(parents=True)
    image = root / f"{name}.squashfs"
    image.write_bytes(b"hsqs")
    conf = "lxc.uts.name = app\n" + (f"lxc.net.0.link = {link}\n" if link else "")
    (b / "lxc.container.conf").write_text(conf)
    aember_package.write_package(
        b / f"{name}.aember", {"name": name, "command": ["/app"]}, conf, image, seed
    )
    entry = {"name": name, **({"dependencies": deps} if deps else {})}
    (b / "container.json").write_text(json.dumps(entry))
    return b


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.overlay = self.root / "rootfs"
        (self.overlay / "etc" / "aember").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def containers(self):
        return json.loads((self.overlay / "etc/aember/containers.json").read_text())

    def test_merge_replaces_the_same_name_and_keeps_the_rest(self):
        cur = {
            "bridges": [{"name": "lxcbr0"}],
            "containers": [{"name": "a"}, {"name": "b", "v": 1}],
        }
        out = merge_entry(cur, {"name": "b", "v": 2})
        self.assertEqual(out["bridges"], [{"name": "lxcbr0"}])
        self.assertEqual(out["containers"], [{"name": "a"}, {"name": "b", "v": 2}])
        self.assertEqual(
            merge_entry({}, {"name": "x"}),
            {"bridges": [], "containers": [{"name": "x"}]},
        )

    def test_overlay_from_an_aember_checkout_or_a_rootfs(self):
        repo = self.root / "repo"
        rootfs = repo / "resources" / "x64-poky-linux" / "rootfs"
        (rootfs / "etc" / "aember").mkdir(parents=True)
        self.assertEqual(overlay_dir(repo, "x64-poky-linux"), rootfs)
        self.assertEqual(overlay_dir(rootfs, "x64-poky-linux"), rootfs)
        with self.assertRaises(RuntimeError):
            overlay_dir(repo / "resources", "x64-poky-linux")

    def test_install_copies_merges_and_warns(self):
        (self.overlay / "etc/aember/services.json").write_text(
            json.dumps({"processes": [{"name": "aember-netd"}]})
        )
        warnings = install(bundle(self.root, link="br9", deps=["db"]), self.overlay)
        self.assertTrue((self.overlay / "var/lib/aember/packages/app.aember").exists())
        self.assertEqual(
            self.containers()["containers"], [{"name": "app", "dependencies": ["db"]}]
        )
        text = " ".join(warnings)
        self.assertIn("aember-containerd", text)
        self.assertIn("br9", text)
        self.assertIn("allow_unsigned", text)

    def test_a_signed_package_needs_its_key_on_the_board(self):
        (self.overlay / "etc/aember/services.json").write_text(
            json.dumps({"processes": [{"name": "aember-containerd"}]})
        )
        b = bundle(self.root, seed=SEED)
        self.assertIn("isn't in", " ".join(install(b, self.overlay)))
        keys = self.overlay / "etc/aember/keys"
        keys.mkdir()
        from aember import ed25519

        (keys / "dev.pub").write_text(
            aember_package.public_key_text(ed25519.public_key(SEED))
        )
        self.assertEqual(install(b, self.overlay), [])

    def test_an_overlay_of_the_old_format_is_not_mixed_in(self):
        (self.overlay / "etc/aember/containers.json").write_text(
            json.dumps({"containers": [{"name": "old", "container": {}}]})
        )
        with self.assertRaisesRegex(RuntimeError, "before .aember packages"):
            install(bundle(self.root), self.overlay)


if __name__ == "__main__":
    unittest.main()
