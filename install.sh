#!/usr/bin/env bash
# One entry point for installing the Klipper monitor and optional Fluidd card.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${KLIPPER_ENV_FILE:-$HOME/printer_data/systemd/klipper.env}"
WEB_ROOT="${FLUIDD_WEB_ROOT:-$HOME/fluidd}"
MOONRAKER_CONFIG="${MOONRAKER_CONFIG:-$HOME/printer_data/config/moonraker.conf}"
UI="ask"

usage() {
    cat <<'EOF'
Usage: ./install.sh [--with-fluidd | --klipper-only]
                    [--env-file PATH] [--web-root PATH]
                    [--moonraker-config PATH]

Installs the update-safe Klipper launcher and, optionally, the included
custom Fluidd dashboard. Does not edit printer.cfg or restart services.
Without an explicit UI option, asks interactively; non-interactive runs
must choose --with-fluidd or --klipper-only.

The Fluidd option backs up the existing web root and disables the stock
Fluidd update-manager section so upstream updates cannot replace the card.
EOF
}

while (($#)); do
    case "$1" in
        --with-fluidd) [[ "$UI" != no ]] || { echo "Conflicting UI options" >&2; exit 2; }; UI=yes; shift ;;
        --klipper-only) [[ "$UI" != yes ]] || { echo "Conflicting UI options" >&2; exit 2; }; UI=no; shift ;;
        --env-file|--web-root|--moonraker-config)
            (($# >= 2)) || { echo "Missing value for $1" >&2; exit 2; }
            case "$1" in
                --env-file) ENV_FILE="$2" ;;
                --web-root) WEB_ROOT="$2" ;;
                --moonraker-config) MOONRAKER_CONFIG="$2" ;;
            esac
            shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ "$UI" == ask ]]; then
    [[ -t 0 ]] || { echo "Choose --with-fluidd or --klipper-only for non-interactive installation." >&2; exit 2; }
    echo "The optional Fluidd card replaces the served Fluidd build with this project's build,"
    echo "backs up the original, and disables the stock Fluidd updater."
    read -r -p "Install the custom Fluidd dashboard too? [y/N] " answer
    case "$answer" in y|Y|yes|YES) UI=yes ;; *) UI=no ;; esac
fi

# Check prerequisites before modifying either installation.
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
[[ -f "$ENV_FILE" ]] || { echo "Klipper environment file not found: $ENV_FILE" >&2; exit 1; }
if [[ "$UI" == yes ]]; then
    [[ -f "$MOONRAKER_CONFIG" ]] || { echo "Moonraker config not found: $MOONRAKER_CONFIG" >&2; exit 1; }
    [[ -f "$REPO_DIR/fluidd/dist/index.html" ]] || { echo "Bundled Fluidd build not found" >&2; exit 1; }
    [[ -d "$WEB_ROOT" ]] || { echo "Fluidd web root not found: $WEB_ROOT" >&2; exit 1; }
fi

"$REPO_DIR/scripts/install.sh" --env-file "$ENV_FILE"
if [[ "$UI" == yes ]]; then
    "$REPO_DIR/scripts/install-fluidd-ui.sh" --web-root "$WEB_ROOT" --moonraker-config "$MOONRAKER_CONFIG"
fi

cat <<EOF

Installation files installed. Before restarting Klipper:
  1. Configure [filament_motion_monitor <name>] in printer.cfg.
     Use this printer's actual sensor pin and existing macros; do not use the
     example pin unchanged. Remove or disable any old sensor using that pin.
  2. Set ticks_per_mm provisionally and clog_detection_length: 0, then
     calibrate this printer independently (see README.md).
  3. Restart the Klipper service (not just FIRMWARE_RESTART).
EOF
if [[ "$UI" == yes ]]; then
    echo "  4. Restart Moonraker and hard-refresh Fluidd (Ctrl+Shift+R)."
fi
