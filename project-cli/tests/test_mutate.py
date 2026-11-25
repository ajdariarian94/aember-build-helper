"""`aember mutate`: the mutants, a run against a fake build, the report and
the isolation of the test runs (no SDK or compiler needed)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from aember_project import Project, cli, mutate

SOURCE = """\
// a == b in a comment stays
#include <vector>
/* block: a && b
   still: true */
bool F(int a, int b) {
  if (a == b && Ready()) return true;
  log("a != b || c");  // string and comment: untouched
  return !Done(a + 1) || b <= 3;
}
"""


class FindMutantsTest(unittest.TestCase):
    def test_operators_outside_comments_and_literals(self):
        found = [(m.line, m.name) for m in mutate.find_mutants("x.cpp", SOURCE)]
        self.assertEqual(
            sorted(found),
            sorted(
                [
                    (6, "eq->ne"),
                    (6, "and->or"),
                    (6, "true->false"),
                    (8, "le->gt"),
                    (8, "or->and"),
                    (8, "plus1->minus1"),
                    (8, "drop-not"),
                ]
            ),
        )

    def test_apply_changes_one_spot_and_refuses_a_stale_mutant(self):
        m = next(m for m in mutate.find_mutants("x.cpp", SOURCE) if m.name == "eq->ne")
        self.assertIn("if (a != b && Ready())", m.apply(SOURCE))
        self.assertEqual(m.apply(SOURCE).count("!="), SOURCE.count("!=") + 1)
        with self.assertRaises(ValueError):
            m.apply(SOURCE.replace("a == b &&", "a <= b &&"))


class FakeRunner:
    """Kills every mutant in a.cpp's line 2, lets the rest survive."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.baselines = 0
        self.builds = 0

    def baseline(self) -> None:
        self.baselines += 1

    def build(self) -> bool:
        self.builds += 1
        return "BROKEN" not in (self.root / "src" / "a.cpp").read_text()

    def test(self) -> str:
        line = (self.root / "src" / "a.cpp").read_text().splitlines()[1]
        return "survived" if "x == 1" in line else "killed"


class MutateRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "src" / "sub").mkdir(parents=True)
        self.original = "int a;\nbool k = x == 1;\nbool s = y == 2;\n"
        (self.root / "src" / "a.cpp").write_text(self.original)
        (self.root / "src" / "main.cpp").write_text("bool m = z == 3;\n")
        (self.root / "src" / "sub" / "b.cpp").write_text("int b;\n")
        self.project = Project("demo", "1.0.0", root=self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sources_skip_main(self):
        self.assertEqual(
            mutate.sources(self.root),
            [self.root / "src" / "a.cpp", self.root / "src" / "sub" / "b.cpp"],
        )

    def test_run_scores_restores_and_reports(self):
        runner = FakeRunner(self.root)
        report = mutate.mutate(self.project, runner=runner)
        self.assertEqual(report["mutants"], 2)
        self.assertEqual(report["score"], 50.0)
        self.assertEqual([m["line"] for m in report["survived"]], [3])
        self.assertEqual(runner.baselines, 1)
        self.assertEqual(runner.builds, 3)  # each mutant, then the original
        self.assertEqual((self.root / "src" / "a.cpp").read_text(), self.original)
        self.assertFalse(list(self.root.rglob("*" + mutate.BACKUP_SUFFIX)))
        out = self.root / "build" / "mutation"
        self.assertEqual(json.loads((out / "demo.json").read_text())["score"], 50.0)
        md = (out / "demo.md").read_text()
        self.assertIn("### demo: 50.0% (2 mutants, 1 survived)", md)
        self.assertIn("| `src/a.cpp:3` | eq->ne | `bool s = y == 2;` |", md)

    def test_sample_and_file_filter(self):
        report = mutate.mutate(
            self.project, max_mutants=1, files=["a.cpp"], runner=FakeRunner(self.root)
        )
        self.assertEqual(report["mutants"], 1)
        with self.assertRaises(FileNotFoundError):
            mutate.mutate(self.project, files=["nope"], runner=FakeRunner(self.root))

    def test_backup_of_a_killed_run_is_restored_first(self):
        backup = self.root / "src" / ("a.cpp" + mutate.BACKUP_SUFFIX)
        backup.write_text(self.original)
        (self.root / "src" / "a.cpp").write_text("BROKEN mutant left behind\n")
        mutate.mutate(self.project, runner=FakeRunner(self.root))
        self.assertEqual((self.root / "src" / "a.cpp").read_text(), self.original)


class IsolationTest(unittest.TestCase):
    def run_py(self, code: str, timeout: float = 10) -> str:
        cmd = [sys.executable, "-c", code]
        return mutate.run_isolated(cmd, Path("/"), {}, timeout)

    def test_a_test_killing_its_process_group_spares_the_run(self):
        kill_own_group = "import os, signal; os.kill(0, signal.SIGKILL)"
        self.assertEqual(self.run_py(kill_own_group), "killed")
        self.assertEqual(self.run_py("pass"), "survived")

    def test_timeout_kills_the_whole_group(self):
        hang = "import subprocess; subprocess.run(['sleep', '30'])"
        self.assertEqual(self.run_py(hang, timeout=0.5), "timeout")


class CliTest(unittest.TestCase):
    def test_mutate_arguments_reach_the_run(self):
        calls = []
        original = mutate.mutate
        mutate.mutate = lambda *a: calls.append(a)
        try:
            p = Project("demo", "1.0.0")
            rc = cli.main(p, ["mutate", "-n", "5", "--seed", "3", "-f", "x", "-f", "y"])
        finally:
            mutate.mutate = original
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [(p, 5, 3, 120.0, ["x", "y"])])


if __name__ == "__main__":
    unittest.main()
