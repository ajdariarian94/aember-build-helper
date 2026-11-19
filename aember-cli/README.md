# aember-cli (aember-build-helper)

The `aember` command of aember-build-helper, laid out like the `aember-cli/`
of aember, aember-resources and aember-website: the package in `aember/`,
the launcher `run.py`, the tests in `tests/`.

Unlike those, it uses only the Python 3.10+ standard library (argparse, no
Typer/rich): it runs from a submodule in someone else's project, with no venv.

```bash
tools/aember-build-helper/aember-cli/run.py init | check | build | install <aember>
```

| Module | Role |
|--------|------|
| `aember/cli.py` | argparse commands: `init`, `check`, `build`, `install` |
| `aember/manifest.py` | `aember-container.json` → `Manifest` (validation, defaults) |
| `aember/contract.py` | aember's side: paths, `lxc.container.conf`, the containers.json entry |
| `aember/rootfs.py` | the rootfs as one tar stream into `mksquashfs - out -tar` |
| `aember/libs.py` | NEEDED + program interpreter from a sysroot (readelf) |
| `aember/install.py` | copy into an overlay, merge containers.json |

Tests (from the repo root): `python3 -m unittest discover -s aember-cli/tests -t aember-cli`.

Don't `pip install` it into aember's dev container venv: that venv's
`aember` package is aember's own CLI. `run.py` puts this directory first on
`sys.path`, so running it directly is always safe.
