import unittest
from pathlib import Path

from aember_build_helper import aember
from aember_build_helper.manifest import parse


def manifest(**kw):
    data = {"name": "app", "rootfs": {"dir": "s"}, "command": ["/app"]}
    data.update(kw)
    return parse(data, Path("/p"))


def conf(**kw) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in aember.lxc_config(manifest(**kw)).splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = (x.strip() for x in line.split("=", 1))
            out.setdefault(k, []).append(v)
    return out


class LxcConfigTest(unittest.TestCase):
    def test_the_rootfs_is_where_containerd_mounts_the_overlay(self):
        c = conf()
        self.assertEqual(c["lxc.rootfs.path"], ["dir:/var/lib/aember/containers/app"])
        self.assertEqual(c["lxc.uts.name"], ["app"])
        self.assertEqual(c["lxc.mount.auto"], ["proc:mixed sys:mixed"])
        self.assertEqual(c["lxc.autodev"], ["1"])

    def test_console_output_goes_to_a_rotating_log(self):
        c = conf()
        self.assertEqual(
            c["lxc.console.logfile"], ["/var/log/aember-container-app.log"]
        )
        self.assertEqual(c["lxc.console.rotate"], ["1"])
        self.assertNotIn("lxc.console.logfile", conf(console_log=False))

    def test_networks(self):
        self.assertEqual(conf()["lxc.net.0.type"], ["none"])  # host
        self.assertEqual(conf(network="isolated")["lxc.net.0.type"], ["empty"])
        c = conf(
            network={
                "bridge": "lxcbr0",
                "address": "10.0.3.9/24",
                "gateway": "10.0.3.1",
            }
        )
        self.assertEqual(c["lxc.net.0.type"], ["veth"])
        self.assertEqual(c["lxc.net.0.link"], ["lxcbr0"])
        self.assertEqual(c["lxc.net.0.ipv4.address"], ["10.0.3.9/24"])
        self.assertEqual(c["lxc.net.0.ipv4.gateway"], ["10.0.3.1"])

    def test_env_workdir_devices_and_raw_lines(self):
        c = conf(
            env={"B": "2", "A": "1"},
            workdir="/srv",
            devices=["/dev/fb0", "/dev/dri"],
            device_allow=["c 29:0 rwm"],
            lxc=["lxc.cap.drop = sys_module"],
        )
        self.assertEqual(c["lxc.environment"], ["A=1", "B=2"])
        self.assertEqual(c["lxc.init.cwd"], ["/srv"])
        self.assertEqual(c["lxc.cgroup2.devices.allow"], ["c 29:0 rwm"])
        self.assertIn(
            "/dev/fb0 dev/fb0 none bind,create=file,optional 0 0", c["lxc.mount.entry"]
        )
        self.assertIn(
            "/dev/dri dev/dri none bind,create=dir,optional 0 0", c["lxc.mount.entry"]
        )
        self.assertEqual(c["lxc.cap.drop"], ["sys_module"])


class EntryTest(unittest.TestCase):
    def test_entry_matches_containers_json(self):
        e = aember.containers_entry(
            manifest(restart_policy="on-failure"), ["/app", "-v"]
        )
        self.assertEqual(e["name"], "app")
        self.assertEqual(e["type"], "container")
        self.assertEqual(
            e["container"],
            {
                "squashfs": "/var/lib/aember/app/app.squashfs",
                "rootfs": "/var/lib/aember/containers/app",
                "config_path": "/var/lib/aember/app/lxc.container.conf",
                "args": ["/app", "-v"],
            },
        )
        self.assertEqual(e["restart_policy"], "on-failure")
        for key in ("init", "stop_timeout", "max_restart_attempts", "restart_delay"):
            self.assertIn(key, e)


if __name__ == "__main__":
    unittest.main()
