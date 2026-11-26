"""
`aember install`: put a built container into an aember board's rootfs
overlay (resources/<arch>/rootfs in the aember repository):

    var/lib/aember/packages/<name>.aember     the package, copied
    etc/aember/containers.json                {"name", "dependencies"} merged

An entry with the same name is replaced; other containers and the bridges
stay. aember-containerd must be in the overlay's services.json; a signed
package needs its public key in etc/aember/keys/, an unsigned one
"allow_unsigned": true in containers.json.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from . import aember_package

log = logging.getLogger("aember.install")

PACKAGES_DIR = Path("var/lib/aember/packages")
KEYS_DIR = Path("etc/aember/keys")


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
    """Copy the bundle's package into @p overlay; returns warnings."""
    entry = json.loads((bundle / "container.json").read_text())
    name = entry["name"]
    package = bundle / f"{name}{aember_package.EXTENSION}"
    dst = overlay / PACKAGES_DIR
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(package, dst / package.name)

    cfg = overlay / "etc" / "aember" / "containers.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    current = json.loads(cfg.read_text()) if cfg.exists() else {}
    for other in current.get("containers", []):
        if "container" in other:
            raise RuntimeError(
                f"{cfg} is in the format before .aember packages (entry "
                f"'{other.get('name')}'): update the aember checkout"
            )
    merged = merge_entry(current, entry)
    cfg.write_text(json.dumps(merged, indent=2) + "\n")

    warnings = []
    services = overlay / "etc" / "aember" / "services.json"
    names = []
    if services.exists():
        data = json.loads(services.read_text())
        listed = data.get("services", data.get("processes", []))
        names = [p.get("name") for p in listed]
    if "aember-containerd" not in names:
        warnings.append(
            "aember-containerd is not in etc/aember/services.json: nothing will "
            "start the container"
        )
    footer = aember_package.read_footer(package)
    if footer.signed:
        keys = aember_package.load_keys(overlay / KEYS_DIR)
        if not any(aember_package.key_id(k) == footer.key_id for k in keys.values()):
            warnings.append(
                f"{package.name} is signed with a key that isn't in "
                f"{KEYS_DIR}: copy its .pub there"
            )
    elif not merged.get("allow_unsigned", False):
        warnings.append(
            f"{package.name} isn't signed and containers.json doesn't say "
            '"allow_unsigned": true: the board will refuse it'
        )
    bridges = {b.get("name") for b in merged["bridges"]}
    for line in (bundle / "lxc.container.conf").read_text().splitlines():
        key, _, value = (x.strip() for x in line.partition("="))
        if key.endswith(".link") and value not in bridges:
            warnings.append(
                f"bridge {value} is not in containers.json 'bridges': add it "
                '(e.g. {"name": "%s", "address": "10.0.3.1/24"})' % value
            )
    return warnings
