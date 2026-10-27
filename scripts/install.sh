#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${KLIPPER_ENV_FILE:-$HOME/printer_data/systemd/klipper.env}"
RESTART=0
while (($#)); do
    case "$1" in
        --env-file) ENV_FILE="$2"; shift 2 ;;
        --restart) RESTART=1; shift ;;
        -h|--help) echo "Usage: $0 [--env-file PATH] [--restart]"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done
[[ -f "$ENV_FILE" ]] || { echo "Klipper environment file not found: $ENV_FILE" >&2; exit 1; }
python3 - "$ENV_FILE" "$REPO_DIR/bootstrap/launch_klipper.py" <<'PY'
import pathlib, shlex, sys, time
env_path = pathlib.Path(sys.argv[1]).expanduser().resolve()
launcher = str(pathlib.Path(sys.argv[2]).resolve())
start = "# >>> klipper-filament-motion-monitor >>>"
end = "# <<< klipper-filament-motion-monitor <<<"
text = env_path.read_text()
original_lines = text.splitlines()
existing_real = None
for line in original_lines:
    if line.startswith("KLIPPER_FILAMENT_MONITOR_REAL_SCRIPT="):
        values = shlex.split(line.split("=", 1)[1].strip())
        existing_real = values[0] if values else None
filtered, in_block = [], False
for line in original_lines:
    if line.strip() == start:
        in_block = True
        continue
    if line.strip() == end:
        in_block = False
        continue
    if not in_block:
        filtered.append(line)
args_index = None
argv = None
for index, line in enumerate(filtered):
    if line.startswith("KLIPPER_ARGS="):
        args_index = index
        raw = line.split("=", 1)[1].strip()
        parsed = shlex.split(raw)
        if not parsed:
            raise SystemExit("KLIPPER_ARGS is empty")
        argv = shlex.split(parsed[0]) if len(parsed) == 1 and " " in parsed[0] else parsed
        break
if args_index is None or argv is None:
    raise SystemExit("KLIPPER_ARGS not found in %s" % env_path)
if pathlib.Path(argv[0]).resolve() == pathlib.Path(launcher):
    real_script = existing_real
    if not real_script:
        raise SystemExit("Existing launcher install is missing the real script path")
else:
    real_script = argv[0]
    argv[0] = launcher
value = " ".join(argv).replace("\\", "\\\\").replace('"', '\\"')
filtered[args_index] = 'KLIPPER_ARGS="%s"' % value
block = [start,
         'KLIPPER_FILAMENT_MONITOR_REAL_SCRIPT="%s"' % real_script,
         end]
new_text = "\n".join(filtered).rstrip() + "\n\n" + "\n".join(block) + "\n"
backup = env_path.with_name(env_path.name + ".filament-monitor-%d.bak" % time.time())
backup.write_text(text)
env_path.write_text(new_text)
print("Updated: %s" % env_path)
print("Backup:  %s" % backup)
print("Klippy:  %s" % real_script)
PY
echo "Installed update-safe launcher from: $REPO_DIR"
if ((RESTART)); then systemctl restart klipper; else echo "A full klipper service restart is required before first use."; fi
