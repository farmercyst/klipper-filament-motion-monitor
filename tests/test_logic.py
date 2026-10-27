import importlib.util
import pathlib
import unittest

MODULE_PATH = (pathlib.Path(__file__).resolve().parents[1]
               / "klippy_extras" / "filament_motion_monitor.py")
SPEC = importlib.util.spec_from_file_location("filament_motion_monitor", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeExtruder:
    def __init__(self, position=0.0):
        self.position = position

    def find_past_position(self, print_time):
        return self.position


class LogicTests(unittest.TestCase):
    def make_monitor(self):
        monitor = MODULE.FilamentMotionMonitor.__new__(
            MODULE.FilamentMotionMonitor)
        monitor.extruder = FakeExtruder()
        monitor.estimated_print_time = lambda eventtime: eventtime
        monitor.last_extruder_position = 0.0
        monitor.commanded_extrusion_length = 0.0
        monitor.commanded_retraction_length = 0.0
        monitor.commanded_motion_length = 0.0
        monitor.forward_since_tick = 0.0
        monitor.ticks_per_mm = 1.0
        monitor.tick_count = 0
        monitor.clog_checkpoint_commanded = 0.0
        monitor.clog_checkpoint_sensor = 0.0
        monitor.clog_window_commanded = 0.0
        monitor.clog_window_sensor = 0.0
        monitor.clog_window_ratio = 1.0
        monitor.clog_detection_length = 10.0
        monitor.clog_min_motion_ratio = 0.7
        monitor.triggered = None
        monitor._trigger_fault = (
            lambda eventtime, reason: setattr(monitor, "triggered", reason))
        return monitor

    def sample_position(self, monitor, position):
        monitor.extruder.position = position
        monitor._sample_extruder(position)

    def test_retract_unretract_does_not_advance_runout_distance(self):
        monitor = self.make_monitor()
        self.sample_position(monitor, -5.0)
        self.sample_position(monitor, 0.0)
        self.assertEqual(monitor.forward_since_tick, 0.0)
        self.sample_position(monitor, 10.0)
        self.assertEqual(monitor.forward_since_tick, 10.0)
        self.assertEqual(monitor.commanded_extrusion_length, 15.0)
        self.assertEqual(monitor.commanded_retraction_length, 5.0)

    def test_clog_check_allows_one_tick_quantization(self):
        monitor = self.make_monitor()
        monitor.commanded_extrusion_length = 10.0
        monitor.tick_count = 6
        monitor._check_clog(1.0)
        self.assertIsNone(monitor.triggered)
        self.assertAlmostEqual(monitor.clog_window_ratio, 0.6)

    def test_clog_check_triggers_below_tolerated_ratio(self):
        monitor = self.make_monitor()
        monitor.commanded_extrusion_length = 10.0
        monitor.tick_count = 5
        monitor._check_clog(1.0)
        self.assertEqual(monitor.triggered, "clog")


if __name__ == "__main__":
    unittest.main()
