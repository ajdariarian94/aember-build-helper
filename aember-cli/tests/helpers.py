import shutil
import subprocess
import unittest


def have_mksquashfs_tar() -> bool:
    tool = shutil.which("mksquashfs")
    if not tool or not shutil.which("unsquashfs"):
        return False
    out = subprocess.run([tool, "-version"], capture_output=True, text=True).stdout
    try:
        major, minor = (int(x) for x in out.split()[2].split(".")[:2])
    except (IndexError, ValueError):
        return False
    return (major, minor) >= (4, 6)


needs_squashfs = unittest.skipUnless(
    have_mksquashfs_tar(), "needs mksquashfs/unsquashfs 4.6+ (squashfs-tools)"
)
needs_gcc = unittest.skipUnless(
    shutil.which("gcc") and shutil.which("readelf"), "needs gcc and readelf"
)
