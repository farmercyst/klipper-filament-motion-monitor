# Fluidd dashboard component

This directory contains a custom Fluidd `v1.37.6-fmm.1` build with a
standalone **Filament Motion** dashboard card.

The card:

- automatically appears when Fluidd sees a `filament_motion_monitor ...`
  Klipper object;
- shows a Happy Hare-inspired 300-degree flow gauge;
- uses the clog comparison-window ratio while that window is active and the
  overall sensed/commanded motion ratio otherwise;
- marks the configured `clog_min_motion_ratio` threshold and the 100% target;
- shows sensed versus commanded filament distance and runout margin;
- enables or disables the monitor with `SET_FILAMENT_SENSOR`.

The first monitor object is displayed. Sensor names are passed through Fluidd's
G-code parameter encoder, so names containing spaces remain safe.

## Install

The repository includes the compiled build, so Node.js is not needed on the
printer:

```bash
cd ~/klipper-filament-motion-monitor
./scripts/install-fluidd-ui.sh --restart
```

The installer moves the existing Fluidd directory to a timestamped backup,
symlinks `~/fluidd` to `fluidd/dist`, and comments out the stock
`[update_manager fluidd]` section. That updater must be disabled because an
official Fluidd update would replace the custom build.

After installation, hard-refresh the browser. Fluidd is a PWA and its service
worker may otherwise continue showing cached assets.

## Rebuild

The source delta is stored in `fluidd-v1.37.6.patch`, based on Fluidd tag
`v1.37.6` / commit `d894c50d580212c245a7c552ae695008c441683b`.

With Node.js 22.12+ or 24 and pnpm 12.5.1 available:

```bash
./scripts/build-fluidd-ui.sh
```

The script clones the pinned upstream source, verifies its commit, applies the
patch, runs lint and type checking, builds Fluidd, and replaces `fluidd/dist`.

## Updating Fluidd

Fluidd does not currently provide a runtime dashboard-plugin API. Updating to a
new upstream Fluidd version therefore requires rebasing the small patch,
rebuilding `fluidd/dist`, testing it, and committing the resulting assets.
The stock web updater intentionally remains disabled while this custom build is
installed.

## License

Fluidd and this modified Fluidd build are distributed under GPL-3.0. The
upstream Fluidd license is included as `FLUIDD-LICENSE`.
