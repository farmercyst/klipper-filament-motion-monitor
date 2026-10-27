Run smoke checks with:

```bash
python -m unittest discover -s tests -v
python -m py_compile klippy_extras/filament_motion_monitor.py bootstrap/launch_klipper.py
```

The live install is verified by restarting the Klipper service and querying:

```text
filament_motion_monitor filament_sensor
```
