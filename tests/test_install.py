import json
import tempfile
import unittest
from pathlib import Path

from aember_build_helper.install import install, merge_entry, overlay_dir


def bundle(root: Path, name="app", link=None) -> Path:
    b = root / "aember-out" / name
    d = b / "overlay" / "var" / "lib" / "aember" / name
    d.mkdir(parents=True)
    (d / f"{name}.squashfs").write_bytes(b"hsqs")
    conf = "lxc.uts.name = app\n" + (f"lxc.net.0.link = {link}\n" if link else "")
    (d / "lxc.container.conf").write_text(conf)
    (b / "container.json").write_text(json.dumps({"name": name, "type": "container"}))
    return b


class InstallTest(unittest.TestCase):
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
        with tempfile.TemporaryDirectory() as t:
            repo = Path(t)
            rootfs = repo / "resources" / "x64-poky-linux" / "rootfs"
            (rootfs / "etc" / "aember").mkdir(parents=True)
            self.assertEqual(overlay_dir(repo, "x64-poky-linux"), rootfs)
            self.assertEqual(overlay_dir(rootfs, "x64-poky-linux"), rootfs)
            with self.assertRaises(RuntimeError):
                overlay_dir(repo / "resources", "x64-poky-linux")

    def test_install_copies_merges_and_warns(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            overlay = root / "rootfs"
            (overlay / "etc" / "aember").mkdir(parents=True)
            (overlay / "etc" / "aember" / "services.json").write_text(
                json.dumps({"processes": [{"name": "aember-netd"}]})
            )
            warnings = install(bundle(root, link="br9"), overlay)
            self.assertTrue((overlay / "var/lib/aember/app/app.squashfs").exists())
            cfg = json.loads((overlay / "etc/aember/containers.json").read_text())
            self.assertEqual([c["name"] for c in cfg["containers"]], ["app"])
            text = " ".join(warnings)
            self.assertIn("aember-containerd", text)
            self.assertIn("br9", text)


if __name__ == "__main__":
    unittest.main()
