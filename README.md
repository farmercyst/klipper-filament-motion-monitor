# Klipper Filament Motion Monitor

Out-of-tree Klipper filament encoder plugin with configurable ticks/mm,
no-motion runout distance, optional partial-motion/clog detection, and detailed
commanded-versus-sensed motion diagnostics.

## Update-safe install

The installer changes Klipper's user-owned environment file so Klipper starts
through a tiny launcher in this repository. On every service start, the launcher
creates or repairs one symlink in `klippy/extras/`, then runs the real
`klippy.py`. If a Klipper update, reset, or repository clean removes that
symlink, the next service start restores it automatically. No tracked Klipper
file is replaced.

```bash
git clone https://github.com/YOUR_NAME/klipper-filament-motion-monitor.git \
  ~/klipper-filament-motion-monitor
cd ~/klipper-filament-motion-monitor
./scripts/install.sh
```

The default environment file is `~/printer_data/systemd/klipper.env`. For a
second instance use `--env-file PATH`. A **full Klipper service restart** is
required after first install; a G-code `RESTART` alone does not reload Python's
startup hook.

## Configuration

```ini
[filament_motion_monitor filament_sensor]
switch_pin: ^host:gpiochip0/gpio73
extruder: extruder
ticks_per_mm: 1.0
runout_length: 15.0

# Set to 0 until ticks_per_mm is calibrated.
clog_detection_length: 50.0
clog_min_motion_ratio: 0.70

pause_on_runout: True
pause_on_clog: True
runout_gcode:
  RESPOND TYPE=error MSG="Filament runout detected"
clog_gcode:
  RESPOND TYPE=error MSG="Possible filament clog detected"
insert_gcode:
  RESPOND MSG="Filament motion restored"
```

- `ticks_per_mm`: digital sensor transitions per mm of actual filament motion.
- `runout_length`: positive commanded extrusion allowed without a sensor tick.
- `clog_detection_length`: comparison-window length; `0` disables clog checks.
- `clog_min_motion_ratio`: minimum sensed/commanded ratio before a clog fault.
- `sample_time`: monitor interval, default `0.25` seconds.
- `reset_on_print_start`: reset diagnostics at print start, default `True`.

A one-wire encoder reports motion but not direction. `sensor_motion_length` is
therefore absolute sensor motion. Positive commanded extrusion and retractions
are reported separately.

## Calibration

Disable clog detection (`clog_detection_length: 0`), then:

1. `RESET_FILAMENT_MONITOR SENSOR=filament_sensor`
2. Move a known length (preferably 100 mm or more) through the sensor without
   retractions.
3. Run `CALIBRATE_FILAMENT_MONITOR SENSOR=filament_sensor LENGTH=100`.
4. Put the recommended `ticks_per_mm` in the config, restart, verify values,
   then enable clog detection.

Without `LENGTH`, calibration uses the plugin's measured positive commanded
extrusion.

## Fluidd diagnostics and commands

The object `filament_motion_monitor filament_sensor` exposes:

- `commanded_extrusion_length`, `sensor_motion_length`, and `difference`
- `motion_ratio`, `ticks`, and `calculated_ticks_per_mm`
- `runout_remaining`
- clog window command/sensor/ratio values
- `state`, `active_fault`, and `last_fault`

Use Fluidd's object/diagnostics view or:

```gcode
QUERY_FILAMENT_MONITOR SENSOR=filament_sensor
RESET_FILAMENT_MONITOR SENSOR=filament_sensor
QUERY_FILAMENT_SENSOR SENSOR=filament_sensor
SET_FILAMENT_SENSOR SENSOR=filament_sensor ENABLE=0
SET_FILAMENT_SENSOR SENSOR=filament_sensor ENABLE=1
SET_FILAMENT_MONITOR SENSOR=filament_sensor TICKS_PER_MM=0.35
```

Runtime settings are not persisted; edit the config after calibration.

## Fluidd dashboard card

A compiled Fluidd `v1.37.6-fmm.1` build is included with a standalone,
Happy Hare-inspired **Filament Motion** flow gauge and an enable/disable toggle.
It automatically detects the first `filament_motion_monitor ...` object and
issues `SET_FILAMENT_SENSOR` for that sensor.

Install it with:

```bash
cd ~/klipper-filament-motion-monitor
./scripts/install-fluidd-ui.sh --restart
```

The installer backs up the stock `~/fluidd`, serves the repository-managed
build through a symlink, and disables the stock Fluidd web updater so an
official update cannot overwrite the custom component. Hard-refresh the browser
after installation because Fluidd's service worker caches compiled assets.

To return to stock Fluidd:

```bash
./scripts/uninstall-fluidd-ui.sh --restart
```

See [`fluidd/README.md`](fluidd/README.md) for build and upstream-update details.

## Moonraker update manager

After pushing this repository to GitHub, add:

```ini
[update_manager filament-motion-monitor]
type: git_repo
path: ~/klipper-filament-motion-monitor
origin: https://github.com/YOUR_NAME/klipper-filament-motion-monitor.git
primary_branch: main
managed_services: klipper
```

## Uninstall

Remove the `[filament_motion_monitor ...]` config section, run
`./scripts/uninstall.sh`, and restart the Klipper service.
