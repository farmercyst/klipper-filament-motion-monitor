#!/usr/bin/env bash
set -euo pipefail
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
python3 - "$ENV_FILE" <<'PY'
import pathlib, shlex, sys
env_path = pathlib.Path(sys.argv[1]).expanduser().resolve()
start = "# >>> klipper-filament-motion-monitor >>>"
end = "# <<< klipper-filament-motion-monitor <<<"
lines = env_path.read_text().splitlines()
real_script = None
for line in lines:
    if line.startswith("KLIPPER_FILAMENT_MONITOR_REAL_SCRIPT="):
        values = shlex.split(line.split("=", 1)[1].strip())
        real_script = values[0] if values else None
out, in_block = [], False
for line in lines:
    if line.strip() == start:
        in_block = True
        continue
    if line.strip() == end:
        in_block = False
        continue
    if in_block:
        continue
    if real_script and line.startswith("KLIPPER_ARGS="):
        parsed = shlex.split(line.split("=", 1)[1].strip())
        argv = shlex.split(parsed[0]) if len(parsed) == 1 and " " in parsed[0] else parsed
        if argv:
            argv[0] = real_script
            value = " ".join(argv).replace("\\", "\\\\").replace('"', '\\"')
            line = 'KLIPPER_ARGS="%s"' % value
    out.append(line)
env_path.write_text("\n".join(out).rstrip() + "\n")
print("Removed launcher from: %s" % env_path)
PY
echo "Remove the plugin config and restart Klipper."
if ((RESTART)); then systemctl restart klipper; fi
