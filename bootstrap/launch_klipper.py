#!/usr/bin/env python3
"""Create/repair the Klipper extras symlink, then run real Klippy."""
import os
import pathlib
import runpy
import sys

repo_dir = pathlib.Path(__file__).resolve().parents[1]
source = repo_dir / "klippy_extras" / "filament_motion_monitor.py"
real_script = pathlib.Path(os.environ.get(
    "KLIPPER_FILAMENT_MONITOR_REAL_SCRIPT",
    str(pathlib.Path.home() / "klipper" / "klippy" / "klippy.py"),
)).expanduser().resolve()

if not real_script.is_file():
    raise SystemExit("Real Klipper script not found: %s" % real_script)
if not source.is_file():
    raise SystemExit("Filament monitor module not found: %s" % source)

destination = real_script.parent / "extras" / source.name
if destination.is_symlink():
    if destination.resolve() != source.resolve():
        destination.unlink()
elif destination.exists():
    raise SystemExit(
        "Refusing to replace non-symlink Klipper extra: %s" % destination)

if not destination.is_symlink():
    temporary = destination.with_name(destination.name + ".tmp-link")
    if temporary.is_symlink() or temporary.exists():
        temporary.unlink()
    temporary.symlink_to(source)
    temporary.replace(destination)

# Match direct execution of klippy.py as closely as possible.
sys.path.insert(0, str(real_script.parent))
sys.argv[0] = str(real_script)
runpy.run_path(str(real_script), run_name="__main__")
