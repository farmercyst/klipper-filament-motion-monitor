#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$REPO_DIR/fluidd/dist"
WEB_ROOT="${FLUIDD_WEB_ROOT:-$HOME/fluidd}"
MOONRAKER_CONFIG="${MOONRAKER_CONFIG:-$HOME/printer_data/config/moonraker.conf}"
STATE_FILE="${FLUIDD_UI_STATE_FILE:-$HOME/printer_data/config/.filament-motion-monitor-fluidd-state.json}"
RESTART=0

while (($#)); do
    case "$1" in
        --web-root) WEB_ROOT="$2"; shift 2 ;;
        --moonraker-config) MOONRAKER_CONFIG="$2"; shift 2 ;;
        --restart) RESTART=1; shift ;;
        -h|--help)
            echo "Usage: $0 [--web-root PATH] [--moonraker-config PATH] [--restart]"
            exit 0
            ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

python3 - "$WEB_ROOT" "$DIST_DIR" "$MOONRAKER_CONFIG" "$STATE_FILE" <<'PY'
import json
import pathlib
import re
import sys

web_root = pathlib.Path(sys.argv[1]).expanduser().absolute()
dist_dir = pathlib.Path(sys.argv[2]).expanduser().resolve()
moonraker_config = pathlib.Path(sys.argv[3]).expanduser().absolute()
state_file = pathlib.Path(sys.argv[4]).expanduser().absolute()

state = {}
if state_file.exists():
    state = json.loads(state_file.read_text())
    web_root = pathlib.Path(state.get("web_root", web_root)).expanduser().absolute()
    moonraker_config = pathlib.Path(
        state.get("moonraker_config", moonraker_config)
    ).expanduser().absolute()

if web_root.is_symlink():
    target = web_root.resolve()
    if target == dist_dir:
        web_root.unlink()
    else:
        raise SystemExit(
            "Refusing to remove unrelated symlink %s -> %s" %
            (web_root, target)
        )
elif web_root.exists():
    raise SystemExit("Refusing to replace non-symlink Fluidd path: %s" % web_root)

backup_value = state.get("web_root_backup")
if backup_value:
    backup = pathlib.Path(backup_value)
    if backup.exists() and not web_root.exists():
        backup.rename(web_root)
        print("Restored upstream Fluidd: %s" % web_root)

start_marker = "# >>> filament-motion-monitor custom Fluidd >>>"
end_marker = "# <<< filament-motion-monitor custom Fluidd <<<"
if moonraker_config.exists():
    lines = moonraker_config.read_text().splitlines()
    try:
        start = lines.index(start_marker)
        end = lines.index(end_marker, start + 1)
    except ValueError:
        pass
    else:
        block = lines[start + 1:end]
        section_start = next(
            (i for i, line in enumerate(block)
             if line.startswith("# [update_manager fluidd]")),
            None
        )
        restored = []
        if section_start is not None:
            for line in block[section_start:]:
                if line.startswith("# "):
                    restored.append(line[2:])
                elif not line.strip():
                    restored.append(line)
                else:
                    break
        lines[start:end + 1] = restored
        moonraker_config.write_text("\n".join(lines).rstrip() + "\n")
        print("Restored stock Fluidd update-manager section: %s" % moonraker_config)

if state_file.exists():
    state_file.unlink()
PY

if ((RESTART)); then
    if ! systemctl restart moonraker; then
        echo "Warning: Moonraker restart needs administrator permission." >&2
        echo "Restart Moonraker from Fluidd's System page or reboot the host." >&2
    fi
else
    echo "Restart Moonraker to restore the stock Fluidd updater in the update panel."
fi
