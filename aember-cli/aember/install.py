"""
`aember install`: put a built container into an aember board's
rootfs overlay (resources/<arch>/rootfs in the aember repository):

    var/lib/aember/<name>/<name>.squashfs, lxc.container.conf   copied
    etc/aember/containers.json                                  entry merged

An entry with the same name is replaced; other containers and the bridges
stay. aember-containerd must be in the overlay's services.json.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

log = logging.getLogger("aember.install")


def overlay_dir(target: Path, arch: str) -> Path:
    """@p target is an aember checkout or an overlay (a rootfs) itself."""
    if (target / "resources" / arch / "rootfs").is_dir():
        return target / "resources" / arch / "rootfs"
    if (target / "etc" / "aember").is_dir() or target.name == "rootfs":
        return target
    raise RuntimeError(
        f"{target}: neither an aember checkout (resources/{arch}/rootfs) nor a "
        "rootfs overlay (etc/aember/)"
    )


def merge_entry(containers_json: dict, entry: dict) -> dict:
    out = dict(containers_json)
    out.setdefault("bridges", [])
    rest = [c for c in out.get("containers", []) if c.get("name") != entry["name"]]
    out["containers"] = [*rest, entry]
    return out


def install(bundle: Path, overlay: Path) -> list[str]:
    """Copy the bundle into @p overlay; returns warnings."""
    entry = json.loads((bundle / "container.json").read_text())
    name = entry["name"]
    src = bundle / "overlay" / "var" / "lib" / "aember" / name
    dst = overlay / "var" / "lib" / "aember" / name
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        shutil.copy2(f, dst / f.name)

    cfg = overlay / "etc" / "aember" / "containers.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    current = json.loads(cfg.read_text()) if cfg.exists() else {}
    cfg.write_text(json.dumps(merge_entry(current, entry), indent=2) + "\n")

    warnings = []
    services = overlay / "etc" / "aember" / "services.json"
    names = []
    if services.exists():
        names = [
            p.get("name") for p in json.loads(services.read_text()).get("processes", [])
        ]
    if "aember-containerd" not in names:
        warnings.append(
            "aember-containerd is not in etc/aember/services.json: nothing will "
            "start the container"
        )
    bridges = {b.get("name") for b in merge_entry(current, entry)["bridges"]}
    for line in (src / "lxc.container.conf").read_text().splitlines():
        key, _, value = (x.strip() for x in line.partition("="))
        if key.endswith(".link") and value not in bridges:
            warnings.append(
                f"bridge {value} is not in containers.json 'bridges': add it "
                '(e.g. {"name": "%s", "address": "10.0.3.1/24"})' % value
            )
    return warnings
