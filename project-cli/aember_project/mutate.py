"""`aember mutate`: mutation testing of the repository's unit tests.

The same small source-level mutator as aember's `aember mutate`
(aember-cli/aember/steps/testing/mutate.py in aember; keep the operator
list in step): one operator at a time in src/**/*.cpp (not main.cpp, which
no unit test links) is turned into its opposite (== / !=, < / >=, && / ||,
true / false, + 1 / - 1, a `!` in front of a call), the unit tests are
rebuilt and run:

- killed: the build or a test failed, or a test hung (timeout);
- survived: every test passed, so no test checks that line.

The original is always put back (a .mutate-backup next to the file is
restored first, so a killed run can't leave a mutant behind). Report:
build/mutation/<project>.json and .md (the survivors with their line).
Slow by nature: --max takes a sample (the same one for the same --seed).
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import shutil
import signal
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from aember_project import build, sdk
from aember_project.project import Project

log = logging.getLogger("aember.mutate")

BACKUP_SUFFIX = ".mutate-backup"

# (pattern, replacement, name). Patterns match whole operators/words only.
MUTATIONS: list[tuple[str, str, str]] = [
    (r"==", "!=", "eq->ne"),
    (r"!=", "==", "ne->eq"),
    (r"(?<![<>=!])<=(?!=)", ">", "le->gt"),
    (r"(?<![<>=!])>=(?!=)", "<", "ge->lt"),
    (r"(?<![<>\-=!])<(?![<=])", ">=", "lt->ge"),
    (r"(?<![<>\-=!])>(?![>=])", "<=", "gt->le"),
    (r"&&", "||", "and->or"),
    (r"\|\|", "&&", "or->and"),
    (r"\btrue\b", "false", "true->false"),
    (r"\bfalse\b", "true", "false->true"),
    (r"\+ 1\b", "- 1", "plus1->minus1"),
    (r"- 1\b", "+ 1", "minus1->plus1"),
    (r"!(?=[A-Za-z_(])", "", "drop-not"),
]

_STRING = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')
# Template brackets and stream/arrow operators look like comparisons: skip
# lines where < or > belong to them.
_NOT_COMPARISON = re.compile(r"template\s*<|#include|->|<<|>>|::|std::\w+<|\w+<\w")
_COMPARISONS = ("lt->ge", "gt->le", "le->gt", "ge->lt")


@dataclass(frozen=True)
class Mutant:
    file: str  # relative to the repository
    line: int  # 1-based
    column: int  # 0-based, in the original line
    original: str
    replacement: str
    name: str

    def apply(self, text: str) -> str:
        lines = text.splitlines(keepends=True)
        line = lines[self.line - 1]
        end = self.column + len(self.original)
        if line[self.column : end] != self.original:
            raise ValueError(f"stale mutant {self}: {line!r}")
        lines[self.line - 1] = line[: self.column] + self.replacement + line[end:]
        return "".join(lines)


def _code_spans(line: str) -> list[tuple[int, int]]:
    """Parts of @p line that are code: outside string/char literals and
    before a // comment."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in _STRING.finditer(line):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(line)))
    result = []
    for start, end in spans:
        comment = line.find("//", start, end)
        if comment >= 0:
            result.append((start, comment))
            break
        result.append((start, end))
    return result


def find_mutants(rel_path: str, text: str) -> list[Mutant]:
    mutants: list[Mutant] = []
    in_block_comment = False
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if in_block_comment:
            in_block_comment = "*/" not in line
            continue
        if stripped.startswith("/*"):
            in_block_comment = "*/" not in stripped
            continue
        if not stripped or stripped.startswith(("//", "*", "#")):
            continue
        skip_angles = bool(_NOT_COMPARISON.search(line))
        taken: set[int] = set()
        for pattern, replacement, name in MUTATIONS:
            if skip_angles and name in _COMPARISONS:
                continue
            for start, end in _code_spans(line):
                for m in re.finditer(pattern, line[start:end]):
                    col = start + m.start()
                    if col not in taken:
                        taken.add(col)
                        mutants.append(
                            Mutant(rel_path, number, col, m.group(0), replacement, name)
                        )
    return mutants


@dataclass
class Result:
    mutant: Mutant
    status: str  # killed | survived | timeout | build-error


def score(results: list[Result]) -> float | None:
    """Killed (incl. timeouts and mutants that don't compile) / all."""
    if not results:
        return None
    killed = sum(r.status != "survived" for r in results)
    return round(100.0 * killed / len(results), 1)


def restore(backup: Path, path: Path) -> None:
    """Put the original back with a new mtime (the backup's older one made
    the build keep the object compiled from the last mutant)."""
    shutil.move(backup, path)
    os.utime(path)


def restore_backups(paths: list[Path]) -> None:
    """Put back originals a killed earlier run left behind."""
    for path in paths:
        backup = path.with_name(path.name + BACKUP_SUFFIX)
        if backup.exists():
            log.warning("Restoring %s from an interrupted run", path)
            restore(backup, path)


def sources(root: Path) -> list[Path]:
    """What the unit tests cover: src/**/*.cpp without main.cpp."""
    return sorted(p for p in (root / "src").rglob("*.cpp") if p.name != "main.cpp")


def report_markdown(name: str, results: list[Result], root: Path) -> str:
    """Score and survivors with their source line (CI job summary)."""
    survived = [r.mutant for r in results if r.status == "survived"]
    lines = [
        f"### {name}: {score(results)}% "
        f"({len(results)} mutants, {len(survived)} survived)",
        "",
    ]
    if survived:
        lines += ["| Where | Mutation | Line |", "|---|---|---|"]
        for m in sorted(survived, key=lambda m: (m.file, m.line, m.column)):
            text = (root / m.file).read_text().splitlines()[m.line - 1].strip()
            code = text.replace("|", "\\|")
            lines.append(f"| `{m.file}:{m.line}` | {m.name} | `{code}` |")
        lines.append("")
    return "\n".join(lines) + "\n"


def run_isolated(cmd: list[str], cwd: Path, env: dict[str, str], timeout: float) -> str:
    """Run @p cmd in its own session (a mutant can make a test kill its own
    process group); on a timeout the whole group goes."""
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        return "timeout"
    return "survived" if code == 0 else "killed"


class Runner:
    """Rebuild and run the unit tests of @p project (host or x64 SDK)."""

    def __init__(self, project: Project, timeout: float) -> None:
        self.project = project
        self.root = project.root
        self.timeout = timeout
        if project.tests == "sdk":
            self.bdir = build.sdk_test_dir(self.root)
        else:
            self.bdir = build.host_test_dir(self.root)

    def baseline(self) -> None:
        """Configure, build and run the tests once, unmutated (raises if
        they don't pass: nothing could be judged)."""
        if self.project.tests == "sdk":
            build.sdk_tests(self.root)
        else:
            build.host_tests(self.root)

    def build(self) -> bool:
        if self.project.tests == "sdk":
            line = sdk.shell(self.root, build.TEST_ARCH, build.build_cmd(self.bdir))
            cmd = ["bash", "-c", line]
        else:
            cmd = ["cmake", "--build", str(self.bdir), "--parallel", str(build.jobs())]
        res = subprocess.run(cmd, cwd=self.root, capture_output=True)
        return res.returncode == 0

    def test(self) -> str:
        if self.project.tests == "sdk":
            commands, env = build.sdk_test_commands(self.root, self.bdir)
        else:
            commands = [["ctest", "--test-dir", str(self.bdir)]]
            env = dict(os.environ)
        for cmd in commands:
            status = run_isolated(cmd, self.root, env, self.timeout)
            if status != "survived":
                return status
        return "survived"


def mutate(
    project: Project,
    max_mutants: int = 0,
    seed: int = 1,
    timeout: float = 120,
    files: list[str] | None = None,
    runner: Runner | None = None,
) -> dict:
    """Run the mutants and write the report; returns it."""
    root = project.root
    srcs = sources(root)
    if files:
        srcs = [s for s in srcs if any(f in str(s) for f in files)]
    if not srcs:
        raise FileNotFoundError(f"No sources to mutate under {root / 'src'}")
    restore_backups(srcs)
    mutants = [
        m
        for s in srcs
        for m in find_mutants(s.relative_to(root).as_posix(), s.read_text())
    ]
    random.Random(seed).shuffle(mutants)
    if max_mutants > 0:
        mutants = mutants[:max_mutants]
    runner = runner or Runner(project, timeout)
    log.info("%d mutants of %d file(s)", len(mutants), len(srcs))
    runner.baseline()

    results: list[Result] = []
    for i, mutant in enumerate(mutants, start=1):
        path = root / mutant.file
        backup = path.with_name(path.name + BACKUP_SUFFIX)
        original = path.read_text()
        shutil.copy2(path, backup)
        try:
            path.write_text(mutant.apply(original))
            status = runner.test() if runner.build() else "build-error"
        finally:
            restore(backup, path)
        results.append(Result(mutant, status))
        log.info(
            "[%d/%d] %-11s %s:%d %s",
            i,
            len(mutants),
            status,
            mutant.file,
            mutant.line,
            mutant.name,
        )
    runner.build()  # the build tree matches the real sources again

    out = root / "build" / "mutation"
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "unit": project.name,
        "score": score(results),
        "mutants": len(results),
        "seed": seed,
        "survived": [asdict(r.mutant) for r in results if r.status == "survived"],
        "results": [{**asdict(r.mutant), "status": r.status} for r in results],
    }
    (out / f"{project.name}.json").write_text(json.dumps(report, indent=2) + "\n")
    (out / f"{project.name}.md").write_text(
        report_markdown(project.name, results, root)
    )
    log.info(
        "Mutation score %s%% (%d mutants, %d survived): %s",
        report["score"],
        len(results),
        len(report["survived"]),
        out / f"{project.name}.json",
    )
    return report
