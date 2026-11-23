"""What one repository tells the shared CLI about itself."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_RESOURCES_REPO = "ajdariarian94/aember-resources"
TEST_MODES = ("host", "sdk")


@dataclass(frozen=True)
class Project:
    """@p name: the container name (must equal aember-container.json's).
    @p resources_version: the aember-resources release whose SDKs it builds
    with. @p tests: "host" (unit tests with the host compiler) or "sdk"
    (built with the x64 SDK and run through its loader, for tests that need
    the SDK's libraries: Qt, wolfSSL). @p root: the repository root (the
    directory with aember-container.json)."""

    name: str
    resources_version: str
    resources_repo: str = DEFAULT_RESOURCES_REPO
    tests: str = "host"
    root: Path = Path(".")

    def __post_init__(self) -> None:
        if self.tests not in TEST_MODES:
            raise ValueError(f"tests must be one of {TEST_MODES}, not {self.tests!r}")
