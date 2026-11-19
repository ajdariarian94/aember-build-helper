import tempfile
import unittest
from pathlib import Path

from aember_build_helper.manifest import Bridge, ManifestError, load, parse

BASE = Path("/proj")


def ok(**kw):
    data = {"name": "app", "rootfs": {"dir": "stage"}, "command": ["/app"]}
    data.update(kw)
    return parse(data, BASE)


class ManifestTest(unittest.TestCase):
    def test_minimal_dir_manifest_gets_aember_defaults(self):
        m = ok()
        self.assertEqual(m.arch, "x64-poky-linux")
        self.assertEqual(m.platform, "linux/amd64")
        self.assertEqual(m.dir, Path("/proj/stage"))
        self.assertEqual(m.network, "host")
        self.assertEqual(
            (m.restart_policy, m.stop_timeout, m.init), ("always", 10, True)
        )
        self.assertEqual(m.compression, "xz")

    def test_paths_are_relative_to_the_manifest(self):
        m = ok(
            files=[{"src": "build/app", "dst": "/usr/bin/app", "mode": "0755"}],
            libs={"sysroot": "/sdk/sysroot"},
        )
        self.assertEqual(m.files[0].src, Path("/proj/build/app"))
        self.assertEqual(m.files[0].mode, 0o755)
        self.assertEqual(m.sysroot, Path("/sdk/sysroot"))

    def test_docker_sources_may_leave_the_command_out(self):
        m = parse({"name": "a", "rootfs": {"docker_image": "alpine:3.20"}}, BASE)
        self.assertIsNone(m.command)
        m = parse({"name": "a", "rootfs": {"dockerfile": "Dockerfile"}}, BASE)
        self.assertEqual(m.context, BASE)

    def test_arch_override_and_platforms(self):
        self.assertEqual(ok(arch="aarch64-poky-linux").platform, "linux/arm64")
        m = parse(
            {"name": "a", "rootfs": {"dir": "x"}, "command": ["/a"]},
            BASE,
            arch="arm-poky-linux",
        )
        self.assertEqual(m.platform, "linux/arm/v7")

    def test_bridge_network(self):
        m = ok(
            network={
                "bridge": "lxcbr0",
                "address": "10.0.3.20/24",
                "gateway": "10.0.3.1",
            }
        )
        self.assertEqual(m.network, Bridge("lxcbr0", "10.0.3.20/24", "10.0.3.1"))

    def test_errors(self):
        bad = [
            {"name": "Bad_Name", "rootfs": {"dir": "x"}, "command": ["/a"]},
            {"name": "a", "rootfs": {}, "command": ["/a"]},
            {"name": "a", "rootfs": {"dir": "x", "docker_image": "y"}, "command": ["/a"]},
            {"name": "a", "rootfs": {"dir": "x"}},  # no command
            {"name": "a", "rootfs": {"dir": "x"}, "command": ["/a"], "arch": "riscv"},
            {"name": "a", "rootfs": {"dir": "x"}, "command": ["/a"], "network": "nat"},
            {"name": "a", "rootfs": {"dir": "x"}, "command": ["/a"], "restart_policy": "x"},
            {"name": "a", "rootfs": {"dir": "x"}, "command": ["/a"], "stop_timeout": -1},
            {"name": "a", "rootfs": {"dir": "x"}, "command": ["/a"], "env": {"A": 1}},
            {"name": "a", "rootfs": {"dir": "x"}, "command": ["/a"], "typo": 1},
            {"name": "a", "rootfs": {"dir": "x"}, "command": ["/a"],
             "files": [{"src": "a", "dst": "relative"}]},
        ]  # fmt: skip
        for data in bad:
            with self.subTest(data=data), self.assertRaises(ManifestError):
                parse(data, BASE)

    def test_load_reports_missing_and_broken_files(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(ManifestError, "not found"):
                load(Path(t) / "nope.json")
            bad = Path(t) / "bad.json"
            bad.write_text("{")
            with self.assertRaisesRegex(ManifestError, "invalid JSON"):
                load(bad)


if __name__ == "__main__":
    unittest.main()
