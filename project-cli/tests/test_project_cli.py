"""The shared container-repo CLI's pure parts: SDK paths, manifests,
argument handling (no SDK, compiler or network needed)."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aember_project import Project, build, cli, sdk


def project_in(tmp: str, **manifest) -> Project:
    """A Project rooted at @p tmp with an aember-container.json."""
    root = Path(tmp)
    (root / "aember-container.json").write_text(
        json.dumps({"name": "demo", "command": ["/usr/bin/demo"], **manifest})
    )
    return Project("demo", "9.8.7", root=root)


class ProjectTest(unittest.TestCase):
    def test_defaults_and_bad_test_mode(self):
        p = Project("demo", "1.2.3")
        self.assertEqual(p.resources_repo, "ajdariarian94/aember-resources")
        self.assertEqual(p.tests, "host")
        with self.assertRaises(ValueError):
            Project("demo", "1.2.3", tests="qemu")


class SdkTest(unittest.TestCase):
    def test_every_aember_architecture_has_a_sysroot(self):
        self.assertEqual(len(sdk.ARCHS), 8)
        for arch in sdk.ARCHS:
            self.assertIn(arch.removesuffix("-musl"), sdk.ARCHS)
            if arch.endswith("-musl"):
                self.assertIn("musl", sdk.SYSROOTS[arch])

    def test_paths_follow_aember_resources_dir(self):
        root = Path("/repo")
        with mock.patch.dict(os.environ, {"AEMBER_RESOURCES_DIR": "/res"}):
            self.assertEqual(
                sdk.env_script(root, "x64-poky-linux"),
                Path("/res/x64-poky-linux/sdk/environment-setup-core2-64-poky-linux"),
            )
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                sdk.sdk_dir(root, "arm-poky-linux"),
                root / "build/aember-resources/arm-poky-linux/sdk",
            )

    def test_installer_url_names_the_release(self):
        p = Project("demo", "9.8.7", resources_repo="me/res")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                sdk.installer_url(p, "riscv64-poky-linux-musl"),
                "https://github.com/me/res/releases/download/v9.8.7/"
                "aember-sdk-riscv64-poky-linux-musl-v9.8.7.sh",
            )
        with mock.patch.dict(os.environ, {"AEMBER_RESOURCES_URL": "file:///r/"}):
            self.assertEqual(
                sdk.installer_url(p, "x64-poky-linux"),
                "file:///r/aember-sdk-x64-poky-linux-v9.8.7.sh",
            )

    def test_unknown_arch_and_missing_sdk_are_errors(self):
        with self.assertRaises(ValueError):
            sdk.sdk_dir(Path("/repo"), "mips-poky-linux")
        with mock.patch.dict(os.environ, {"AEMBER_RESOURCES_DIR": "/nonexistent"}):
            with self.assertRaises(FileNotFoundError):
                sdk.shell(Path("/repo"), "x64-poky-linux", "true")

    def test_sdk_shell_clears_ld_library_path_and_sources_the_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"AEMBER_RESOURCES_DIR": tmp}):
                script = sdk.env_script(Path("/repo"), "x64-poky-linux")
                script.parent.mkdir(parents=True)
                script.write_text("export AEMBER_SDK_TEST=1\n")
                cmd = sdk.shell(Path("/repo"), "x64-poky-linux", "echo hi")
        self.assertTrue(cmd.startswith("unset LD_LIBRARY_PATH; . "))
        self.assertTrue(cmd.endswith("&& echo hi"))


class ManifestTest(unittest.TestCase):
    def test_container_manifest_per_arch(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = project_in(tmp, files=[{"src": "conf/a.json", "dst": "/etc/a"}])
            with mock.patch.dict(os.environ, {"AEMBER_RESOURCES_DIR": "/res"}):
                path = build.container_manifest(p, "aarch64-poky-linux-musl")
            m = json.loads(path.read_text())
            self.assertEqual(m["arch"], "aarch64-poky-linux-musl")
            self.assertEqual(
                m["libs"]["sysroot"],
                "/res/aarch64-poky-linux-musl/sdk/sysroots/cortexa53-poky-linux-musl",
            )
            self.assertEqual(
                m["rootfs"]["dir"], str(p.root / "build/stage/aarch64-poky-linux-musl")
            )
            self.assertEqual(
                m["files"][0]["src"], str(p.root.resolve() / "conf/a.json")
            )

    def test_sysroot_files_and_optional_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = project_in(
                tmp,
                files=[
                    {"src": "{sysroot}/etc/a", "dst": "/etc/a"},
                    {"src": "{sysroot}/nope", "dst": "/n", "optional": True},
                ],
            )
            with mock.patch.dict(os.environ, {"AEMBER_RESOURCES_DIR": "/res"}):
                m = json.loads(
                    build.container_manifest(p, "x64-poky-linux").read_text()
                )
        self.assertEqual(
            m["files"],
            [
                {
                    "src": "/res/x64-poky-linux/sdk/sysroots/core2-64-poky-linux/etc/a",
                    "dst": "/etc/a",
                }
            ],
        )

    def test_manifest_name_must_match_the_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = project_in(tmp)
            other = Project("other", p.resources_version, root=p.root)
            with self.assertRaises(ValueError):
                build.container_manifest(other, "x64-poky-linux")


class CliTest(unittest.TestCase):
    def test_jobs_default_and_override(self):
        with mock.patch.dict(os.environ, {"AEMBER_BUILD_JOBS": "3"}):
            self.assertEqual(build.jobs(), 3)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertGreaterEqual(build.jobs(), 1)

    def test_unknown_arch_is_rejected_by_argparse(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.main(Project("demo", "1.0.0"), ["build", "-a", "mips"])

    def test_pack_without_stage_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(cli.main(project_in(tmp), ["pack"]), 1)

    def test_the_packing_cli_is_in_this_checkout(self):
        self.assertTrue(build.BUILD_HELPER.is_file())


if __name__ == "__main__":
    unittest.main()
