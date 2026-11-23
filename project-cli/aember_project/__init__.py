"""The `aember` CLI of a C++ container repository built with the
aember-resources SDKs (aember-stats, aember-monitor, aember-auth,
aember-fleet's agent): sdk, build, pack, install, test, all.

The repository keeps only `aember-cli/run.py`, which names the project and
calls `main`:

    from aember_project import Project, main
    NAME = "aember-stats"
    RESOURCES_VERSION = "0.1.13"
    TESTS = "host"
    sys.exit(main(Project(NAME, RESOURCES_VERSION, tests=TESTS, root=ROOT)))
"""

from aember_project.cli import main
from aember_project.project import Project

__all__ = ["Project", "main"]
