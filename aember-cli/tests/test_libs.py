import subprocess
import tempfile
import unittest
from pathlib import Path

from aember import libs

from .helpers import needs_gcc


@needs_gcc
class LibsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        (t / "m.c").write_text(
            "#include <math.h>\n#include <stdio.h>\n"
            'int main(int c,char**v){printf("%f\\n",cos(c));return 0;}\n'
        )
        self.exe = t / "m"
        subprocess.run(["gcc", "-o", str(self.exe), str(t / "m.c"), "-lm"], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_interpreter_and_needed_from_the_sysroot(self):
        found = libs.resolve([self.exe], Path("/"))
        names = {Path(p).name for p in found}
        self.assertIn("libc.so.6", names)
        self.assertIn("libm.so.6", names)
        self.assertTrue(any(n.startswith("ld-linux") for n in names), names)
        for dst, src in found.items():
            self.assertTrue(dst.startswith("/"))
            self.assertTrue(src.exists())

    def test_missing_libraries_are_listed(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaisesRegex(RuntimeError, "libc.so.6"):
                libs.resolve([self.exe], Path(empty))

    def test_is_elf(self):
        self.assertTrue(libs.is_elf(self.exe))
        self.assertFalse(libs.is_elf(Path(self.tmp.name) / "m.c"))


if __name__ == "__main__":
    unittest.main()
