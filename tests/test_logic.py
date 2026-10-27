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
    def make_monitor(self, clog_length=10.0, flow_samples=20):
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
        monitor.clog_detection_length = clog_length
        monitor.clog_min_motion_ratio = 0.7
        monitor.flowrate_samples = flow_samples
        monitor.flow_samples = []
        monitor.flow_last_encoder_position = 0.0
        monitor.smoothed_flow_ratio = 0.0
        monitor.sensor_enabled = True
        monitor.is_printing = True
        monitor.active_fault = ""
        monitor.runout_length = 100.0
        monitor.last_tick_time = 0.0
        monitor.last_fault = ""
        monitor.last_fault_time = None
        monitor.filament_present = True
        monitor.triggered = None
        monitor._trigger_fault = (
            lambda eventtime, reason: setattr(monitor, "triggered", reason))
        return monitor

    def sample_position(self, monitor, position, *, periodic=False):
        monitor.extruder.position = position
        monitor._sample_extruder(position, update_flow=periodic)

    def add_flow_pair(self, monitor, encoder, extruder):
        monitor.tick_count = encoder
        monitor._record_flow_sample(extruder)

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

    def test_flow_startup_smoothing_matches_encoder_ramp(self):
        monitor = self.make_monitor()
        self.add_flow_pair(monitor, 10, 10.0)
        self.assertEqual(monitor.smoothed_flow_ratio, 0.5)
        self.add_flow_pair(monitor, 20, 20.0)
        self.assertEqual(monitor.smoothed_flow_ratio, 0.75)
        self.add_flow_pair(monitor, 30, 30.0)
        self.assertEqual(monitor._flow_rate_percent(), 88)

    def test_retained_window_is_bounded_and_adapts_to_slip(self):
        monitor = self.make_monitor(flow_samples=5)
        for point in range(1, 6):
            self.add_flow_pair(monitor, point * 10, float(point * 10))
        self.assertEqual(len(monitor.flow_samples), 5)
        for point in range(6, 11):
            self.add_flow_pair(monitor, point * 10, float(point * 10 + (point - 5) * 10))
        self.assertEqual(len(monitor.flow_samples), 5)
        self.assertLess(monitor.smoothed_flow_ratio, 1.0)

    def test_no_encoder_motion_holds_last_flow(self):
        monitor = self.make_monitor()
        self.add_flow_pair(monitor, 10, 10.0)
        before = (monitor.smoothed_flow_ratio, list(monitor.flow_samples))
        self.sample_position(monitor, 50.0, periodic=True)
        self.assertEqual((monitor.smoothed_flow_ratio, monitor.flow_samples), before)

    def test_nonpositive_signed_displacement_uses_ratio_one(self):
        monitor = self.make_monitor()
        self.add_flow_pair(monitor, 10, 10.0)
        self.add_flow_pair(monitor, 20, 8.0)
        self.assertEqual(monitor.smoothed_flow_ratio, 0.75)

    def test_percentage_is_capped_and_nonfinite_safe(self):
        monitor = self.make_monitor()
        monitor.smoothed_flow_ratio = 2.5
        self.assertEqual(monitor._flow_rate_percent(), 100)
        for value in (float("nan"), float("inf"), -float("inf")):
            monitor.smoothed_flow_ratio = value
            self.assertEqual(monitor._flow_rate_percent(), 0)

    def test_explicit_rebase_clears_samples_and_startup_state(self):
        monitor = self.make_monitor()
        self.add_flow_pair(monitor, 10, 10.0)
        monitor._reset_flow_telemetry(20.0)
        self.assertEqual(monitor.flow_samples, [])
        self.assertEqual(monitor.smoothed_flow_ratio, 0.0)
        self.assertEqual(monitor.flow_last_encoder_position, 10.0)
        monitor.tick_count = 11
        monitor._record_flow_sample(21.0)
        self.assertEqual(monitor._flow_rate_percent(), 50)

    def test_flow_works_when_clog_detection_is_disabled(self):
        monitor = self.make_monitor(clog_length=0.0)
        monitor.tick_count = 10
        monitor.extruder.position = 10.0
        monitor._sample_extruder(10.0, update_flow=True)
        self.assertEqual(monitor.clog_detection_length, 0.0)
        self.assertEqual(monitor._flow_rate_percent(), 50)

    def test_callbacks_and_status_reads_do_not_duplicate_flow_samples(self):
        monitor = self.make_monitor()
        monitor.tick_count = 5
        monitor.extruder.position = 5.0
        monitor._sample_extruder(5.0)
        self.assertEqual(monitor.flow_samples, [])
        monitor._sample_extruder(6.0, update_flow=True)
        monitor._sample_extruder(7.0)
        before = (list(monitor.flow_samples), monitor.smoothed_flow_ratio)
        monitor.get_status(7.0)
        monitor.get_status(8.0)
        self.assertEqual((monitor.flow_samples, monitor.smoothed_flow_ratio), before)

    def test_calibration_baseline_rebases_flow_without_changing_counters(self):
        monitor = self.make_monitor()
        monitor.tick_count = 12
        monitor.commanded_extrusion_length = 45.0
        self.add_flow_pair(monitor, 10, 10.0)
        monitor.tick_count = 12
        monitor.ticks_per_mm = 2.0
        monitor._reset_monitoring_baselines()
        self.assertEqual(monitor.tick_count, 12)
        self.assertEqual(monitor.commanded_extrusion_length, 45.0)
        self.assertEqual(monitor.flow_samples, [])
        self.assertEqual(monitor.smoothed_flow_ratio, 0.0)
        self.assertEqual(monitor.flow_last_encoder_position, 6.0)

    def test_healthy_flow_and_runout_margin_are_independent(self):
        monitor = self.make_monitor()
        monitor.smoothed_flow_ratio = 0.92
        monitor.forward_since_tick = 4.0
        self.assertEqual(monitor._flow_rate_percent(), 92)
        margin = max(0.0, monitor.runout_length - monitor.forward_since_tick)
        self.assertEqual(margin, 96.0)
        monitor.forward_since_tick = 30.0
        self.assertEqual(monitor._flow_rate_percent(), 92)


if __name__ == "__main__":
    unittest.main()
