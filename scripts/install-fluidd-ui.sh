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

[[ -f "$DIST_DIR/index.html" ]] || {
    echo "Fluidd build not found at: $DIST_DIR" >&2
    exit 1
}
[[ -f "$MOONRAKER_CONFIG" ]] || {
    echo "Moonraker config not found at: $MOONRAKER_CONFIG" >&2
    exit 1
}

python3 - "$WEB_ROOT" "$DIST_DIR" "$MOONRAKER_CONFIG" "$STATE_FILE" <<'PY'
import json
import os
import pathlib
import re
import shutil
import sys
import time

web_root = pathlib.Path(sys.argv[1]).expanduser().absolute()
dist_dir = pathlib.Path(sys.argv[2]).expanduser().resolve()
moonraker_config = pathlib.Path(sys.argv[3]).expanduser().resolve()
state_file = pathlib.Path(sys.argv[4]).expanduser().absolute()
state_file.parent.mkdir(parents=True, exist_ok=True)

state = {}
if state_file.exists():
    try:
        state = json.loads(state_file.read_text())
    except (ValueError, OSError):
        state = {}

backup_path = state.get("web_root_backup")
if web_root.is_symlink():
    current_target = web_root.resolve()
    if current_target != dist_dir:
        raise SystemExit(
            "Refusing to replace unrelated symlink %s -> %s" %
            (web_root, current_target)
        )
elif web_root.exists():
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = web_root.with_name(web_root.name + ".upstream-" + stamp)
    web_root.rename(backup)
    backup_path = str(backup)
elif not web_root.parent.exists():
    web_root.parent.mkdir(parents=True)

if not web_root.exists():
    web_root.symlink_to(dist_dir, target_is_directory=True)

start_marker = "# >>> filament-motion-monitor custom Fluidd >>>"
end_marker = "# <<< filament-motion-monitor custom Fluidd <<<"
text = moonraker_config.read_text()
config_backup = state.get("moonraker_config_backup")

if start_marker not in text:
    lines = text.splitlines()
    start_index = None
    end_index = None
    section_pattern = re.compile(r"^\s*\[([^]]+)\]\s*$")

    for index, line in enumerate(lines):
        match = section_pattern.match(line)
        if match and match.group(1).strip().lower() == "update_manager fluidd":
            start_index = index
            for next_index in range(index + 1, len(lines)):
                if section_pattern.match(lines[next_index]):
                    end_index = next_index
                    break
            if end_index is None:
                end_index = len(lines)
            break

    if start_index is not None:
        stamp = int(time.time())
        backup = moonraker_config.with_name(
            moonraker_config.name + ".fluidd-ui-%d.bak" % stamp
        )
        shutil.copy2(moonraker_config, backup)
        config_backup = str(backup)

        section = lines[start_index:end_index]
        commented = [line if not line.strip() else "# " + line for line in section]
        replacement = [
            start_marker,
            "# The stock Fluidd web updater is disabled because it would replace",
            "# the custom dashboard build. Rebuild from this repository instead.",
            *commented,
            end_marker,
            ""
        ]
        lines[start_index:end_index] = replacement
        moonraker_config.write_text("\n".join(lines).rstrip() + "\n")

state.update({
    "web_root": str(web_root),
    "custom_dist": str(dist_dir),
    "web_root_backup": backup_path,
    "moonraker_config": str(moonraker_config),
    "moonraker_config_backup": config_backup
})
state_file.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")

print("Fluidd web root: %s -> %s" % (web_root, dist_dir))
if backup_path:
    print("Upstream backup: %s" % backup_path)
print("Moonraker config: %s" % moonraker_config)
print("State file: %s" % state_file)
PY

if ((RESTART)); then
    if ! systemctl restart moonraker; then
        echo "Warning: Moonraker restart needs administrator permission." >&2
        echo "Restart Moonraker from Fluidd's System page or reboot the host." >&2
    fi
else
    echo "Restart Moonraker to remove the stock Fluidd updater from the update panel."
fi

echo "Hard-refresh Fluidd once if the service worker still shows the old UI."
