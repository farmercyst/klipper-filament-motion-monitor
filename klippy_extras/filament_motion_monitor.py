# Enhanced filament motion monitor for Klipper
#
# Copyright (C) 2026
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging


DEFAULT_SAMPLE_TIME = 0.250


class FilamentMotionMonitor:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object("gcode")
        self.name = config.get_name().split()[-1]

        # Sensor and detection configuration.
        self.switch_pin = config.get("switch_pin")
        self.extruder_name = config.get("extruder", "extruder")
        self.ticks_per_mm = config.getfloat("ticks_per_mm", above=0.0)
        self.runout_length = config.getfloat(
            "runout_length", 7.0, above=0.0)
        self.clog_detection_length = config.getfloat(
            "clog_detection_length", 0.0, minval=0.0)
        self.clog_min_motion_ratio = config.getfloat(
            "clog_min_motion_ratio", 0.70, minval=0.0, maxval=1.0)
        self.sample_time = config.getfloat(
            "sample_time", DEFAULT_SAMPLE_TIME, above=0.0)
        self.reset_on_print_start = config.getboolean(
            "reset_on_print_start", True)

        # Fault actions. pause_on_clog defaults to pause_on_runout.
        self.pause_on_runout = config.getboolean("pause_on_runout", True)
        self.pause_on_clog = config.getboolean(
            "pause_on_clog", self.pause_on_runout)
        if self.pause_on_runout or self.pause_on_clog:
            self.printer.load_object(config, "pause_resume")
        self.pause_delay = config.getfloat("pause_delay", 0.5, above=0.0)
        self.event_delay = config.getfloat("event_delay", 3.0, minval=0.0)

        gcode_macro = self.printer.load_object(config, "gcode_macro")
        self.runout_gcode = self._load_template(
            config, gcode_macro, "runout_gcode")
        self.clog_gcode = self._load_template(
            config, gcode_macro, "clog_gcode")
        self.insert_gcode = self._load_template(
            config, gcode_macro, "insert_gcode")

        # Every digital input transition is one sensor tick.
        buttons = self.printer.load_object(config, "buttons")
        buttons.register_buttons([self.switch_pin], self._encoder_event)

        self.extruder = None
        self.estimated_print_time = None
        self.sample_timer = None

        self.sensor_enabled = True
        self.is_printing = False
        self.filament_present = True
        self.active_fault = ""
        self.last_fault = ""
        self.last_fault_time = None
        self.min_event_systime = self.reactor.NEVER
        self.last_extruder_position = None
        self.last_tick_time = None
        self.tick_count = 0
        self.commanded_extrusion_length = 0.0
        self.commanded_retraction_length = 0.0
        self.commanded_motion_length = 0.0
        self.forward_since_tick = 0.0
        self.clog_checkpoint_commanded = 0.0
        self.clog_checkpoint_sensor = 0.0
        self.clog_window_commanded = 0.0
        self.clog_window_sensor = 0.0
        self.clog_window_ratio = 1.0

        self.printer.register_event_handler("klippy:ready", self._handle_ready)
        self.printer.register_event_handler(
            "idle_timeout:printing", self._handle_printing)
        self.printer.register_event_handler(
            "idle_timeout:ready", self._handle_not_printing)
        self.printer.register_event_handler(
            "idle_timeout:idle", self._handle_not_printing)

        self.gcode.register_mux_command(
            "QUERY_FILAMENT_SENSOR", "SENSOR", self.name,
            self.cmd_QUERY_FILAMENT_SENSOR,
            desc=self.cmd_QUERY_FILAMENT_SENSOR_help)
        self.gcode.register_mux_command(
            "SET_FILAMENT_SENSOR", "SENSOR", self.name,
            self.cmd_SET_FILAMENT_SENSOR,
            desc=self.cmd_SET_FILAMENT_SENSOR_help)
        self.gcode.register_mux_command(
            "QUERY_FILAMENT_MONITOR", "SENSOR", self.name,
            self.cmd_QUERY_FILAMENT_MONITOR,
            desc=self.cmd_QUERY_FILAMENT_MONITOR_help)
        self.gcode.register_mux_command(
            "SET_FILAMENT_MONITOR", "SENSOR", self.name,
            self.cmd_SET_FILAMENT_MONITOR,
            desc=self.cmd_SET_FILAMENT_MONITOR_help)
        self.gcode.register_mux_command(
            "RESET_FILAMENT_MONITOR", "SENSOR", self.name,
            self.cmd_RESET_FILAMENT_MONITOR,
            desc=self.cmd_RESET_FILAMENT_MONITOR_help)
        self.gcode.register_mux_command(
            "CALIBRATE_FILAMENT_MONITOR", "SENSOR", self.name,
            self.cmd_CALIBRATE_FILAMENT_MONITOR,
            desc=self.cmd_CALIBRATE_FILAMENT_MONITOR_help)

    def _load_template(self, config, gcode_macro, option):
        if config.get(option, None) is None:
            return None
        return gcode_macro.load_template(config, option)

    def _sensor_length(self):
        return self.tick_count / self.ticks_per_mm

    def _get_extruder_position(self, eventtime):
        print_time = self.estimated_print_time(eventtime)
        return self.extruder.find_past_position(print_time)

    def _sample_extruder(self, eventtime):
        if self.extruder is None:
            return
        position = self._get_extruder_position(eventtime)
        if self.last_extruder_position is None:
            self.last_extruder_position = position
            return
        delta = position - self.last_extruder_position
        self.last_extruder_position = position
        if delta > 0.0:
            self.commanded_extrusion_length += delta
            self.commanded_motion_length += delta
            self.forward_since_tick += delta
        elif delta < 0.0:
            distance = -delta
            self.commanded_retraction_length += distance
            self.commanded_motion_length += distance
            # Match Klipper's existing motion-sensor behavior: retain signed
            # net travel so a retract followed by an unretract does not count
            # as new forward travel beyond the last encoder tick.
            self.forward_since_tick -= distance

    def _reset_monitoring_baselines(self):
        self.forward_since_tick = 0.0
        self.clog_checkpoint_commanded = self.commanded_extrusion_length
        self.clog_checkpoint_sensor = self._sensor_length()
        self.clog_window_commanded = 0.0
        self.clog_window_sensor = 0.0
        self.clog_window_ratio = 1.0

    def _reset_counters(self, eventtime):
        if self.extruder is not None:
            self.last_extruder_position = self._get_extruder_position(eventtime)
        else:
            self.last_extruder_position = None
        self.tick_count = 0
        self.commanded_extrusion_length = 0.0
        self.commanded_retraction_length = 0.0
        self.commanded_motion_length = 0.0
        self.last_tick_time = eventtime
        self.active_fault = ""
        self.filament_present = True
        self._reset_monitoring_baselines()

    def _handle_ready(self):
        self.extruder = self.printer.lookup_object(self.extruder_name)
        self.estimated_print_time = self.printer.lookup_object(
            "mcu").estimated_print_time
        now = self.reactor.monotonic()
        self._reset_counters(now)
        self.min_event_systime = now + 2.0
        self.sample_timer = self.reactor.register_timer(
            self._sample_event, self.reactor.NEVER)

    def _handle_printing(self, print_time):
        now = self.reactor.monotonic()
        was_printing = self.is_printing
        self.is_printing = True
        if self.reset_on_print_start and not was_printing:
            self._reset_counters(now)
        else:
            self.last_extruder_position = self._get_extruder_position(now)
            self._reset_monitoring_baselines()
        self.reactor.update_timer(self.sample_timer, self.reactor.NOW)

    def _handle_not_printing(self, print_time):
        now = self.reactor.monotonic()
        if self.is_printing:
            self._sample_extruder(now)
        self.is_printing = False
        if self.sample_timer is not None:
            self.reactor.update_timer(self.sample_timer, self.reactor.NEVER)

    def _sample_event(self, eventtime):
        self._sample_extruder(eventtime)
        if self.sensor_enabled and self.is_printing and not self.active_fault:
            if self.forward_since_tick >= self.runout_length:
                self._trigger_fault(eventtime, "runout")
            elif self.clog_detection_length > 0.0:
                self._check_clog(eventtime)
        return eventtime + self.sample_time

    def _check_clog(self, eventtime):
        commanded = (self.commanded_extrusion_length
                     - self.clog_checkpoint_commanded)
        if commanded < self.clog_detection_length:
            return
        sensed = self._sensor_length() - self.clog_checkpoint_sensor
        ratio = sensed / commanded if commanded > 0.0 else 1.0
        self.clog_window_commanded = commanded
        self.clog_window_sensor = sensed
        self.clog_window_ratio = ratio
        # Permit one encoder tick of quantization error at the window edge.
        tolerated_ratio = ((sensed + 1.0 / self.ticks_per_mm) / commanded
                           if commanded > 0.0 else 1.0)
        if tolerated_ratio < self.clog_min_motion_ratio:
            self._trigger_fault(eventtime, "clog")
            return
        # Consecutive windows prevent old good movement masking a new clog.
        self.clog_checkpoint_commanded = self.commanded_extrusion_length
        self.clog_checkpoint_sensor = self._sensor_length()

    def _encoder_event(self, eventtime, state):
        if self.extruder is None:
            return
        now = self.reactor.monotonic()
        if self.is_printing:
            self._sample_extruder(now)
        was_present = self.filament_present
        self.tick_count += 1
        self.last_tick_time = now
        self.forward_since_tick = 0.0
        self.filament_present = True

        # Keep faults latched during a print so diagnostics retain the cause.
        if not self.is_printing and (self.active_fault or not was_present):
            self.active_fault = ""
            if (now >= self.min_event_systime and self.sensor_enabled
                    and self.insert_gcode is not None):
                self.min_event_systime = self.reactor.NEVER
                logging.info(
                    "Filament monitor %s: insert event detected", self.name)
                self.reactor.register_callback(self._insert_event_handler)

    def _trigger_fault(self, eventtime, reason):
        if (eventtime < self.min_event_systime or not self.sensor_enabled
                or not self.is_printing or self.active_fault):
            return
        self.active_fault = reason
        self.last_fault = reason
        self.last_fault_time = eventtime
        self.filament_present = False
        self.min_event_systime = self.reactor.NEVER
        logging.info(
            "Filament monitor %s: %s detected at E+%.3fmm, sensor %.3fmm",
            self.name, reason, self.commanded_extrusion_length,
            self._sensor_length())
        self.reactor.register_callback(
            lambda callback_time, fault=reason:
                self._fault_event_handler(callback_time, fault))

    def _fault_event_handler(self, eventtime, reason):
        should_pause = (self.pause_on_clog if reason == "clog"
                        else self.pause_on_runout)
        prefix = ""
        if should_pause:
            pause_resume = self.printer.lookup_object("pause_resume")
            pause_resume.send_pause_command()
            prefix = "PAUSE\n"
            self.reactor.pause(eventtime + self.pause_delay)
        template = self.clog_gcode if reason == "clog" else self.runout_gcode
        if reason == "clog" and template is None:
            template = self.runout_gcode
        self._exec_gcode(prefix, template)

    def _insert_event_handler(self, eventtime):
        self._exec_gcode("", self.insert_gcode)

    def _exec_gcode(self, prefix, template):
        try:
            script = prefix
            if template is not None:
                script += template.render()
            if script.strip():
                self.gcode.run_script(script + "\nM400")
        except Exception:
            logging.exception("Filament monitor script execution error")
        self.min_event_systime = self.reactor.monotonic() + self.event_delay

    def get_status(self, eventtime):
        sensor_length = self._sensor_length()
        difference = self.commanded_extrusion_length - sensor_length
        if self.commanded_extrusion_length > 0.0:
            ratio = sensor_length / self.commanded_extrusion_length
            calibrated_ticks = self.tick_count / self.commanded_extrusion_length
        else:
            ratio = 0.0
            calibrated_ticks = 0.0
        if not self.sensor_enabled:
            state = "disabled"
        elif self.active_fault:
            state = self.active_fault
        elif self.is_printing:
            state = "monitoring"
        else:
            state = "idle"
        seconds_since_motion = 0.0
        if self.last_tick_time is not None:
            seconds_since_motion = max(0.0, eventtime - self.last_tick_time)
        seconds_since_fault = 0.0
        if self.last_fault_time is not None:
            seconds_since_fault = max(0.0, eventtime - self.last_fault_time)
        return {
            "enabled": bool(self.sensor_enabled),
            "filament_detected": bool(self.filament_present),
            "state": state,
            "printing": bool(self.is_printing),
            "active_fault": self.active_fault,
            "last_fault": self.last_fault,
            "ticks": self.tick_count,
            "ticks_per_mm": self.ticks_per_mm,
            "sensor_motion_length": sensor_length,
            "commanded_extrusion_length": self.commanded_extrusion_length,
            "commanded_retraction_length": self.commanded_retraction_length,
            "commanded_motion_length": self.commanded_motion_length,
            "difference": difference,
            "motion_ratio": ratio,
            "calculated_ticks_per_mm": calibrated_ticks,
            "runout_length": self.runout_length,
            "distance_since_tick": max(0.0, self.forward_since_tick),
            "runout_remaining": max(
                0.0, self.runout_length
                - max(0.0, self.forward_since_tick)),
            "clog_detection_enabled": self.clog_detection_length > 0.0,
            "clog_detection_length": self.clog_detection_length,
            "clog_min_motion_ratio": self.clog_min_motion_ratio,
            "clog_window_commanded": self.clog_window_commanded,
            "clog_window_sensor": self.clog_window_sensor,
            "clog_window_difference": (
                self.clog_window_commanded - self.clog_window_sensor),
            "clog_window_ratio": self.clog_window_ratio,
            "seconds_since_motion": seconds_since_motion,
            "seconds_since_fault": seconds_since_fault,
        }

    def _respond_status(self, gcmd):
        status = self.get_status(self.reactor.monotonic())
        gcmd.respond_info(
            ("Filament monitor %s: state=%s enabled=%s ticks=%d\n"
             "commanded=%.3fmm sensed=%.3fmm diff=%.3fmm ratio=%.3f\n"
             "runout_remaining=%.3fmm last_fault=%s\n"
             "calculated_ticks_per_mm=%.6f")
            % (self.name, status["state"], status["enabled"],
               status["ticks"], status["commanded_extrusion_length"],
               status["sensor_motion_length"], status["difference"],
               status["motion_ratio"], status["runout_remaining"],
               status["last_fault"] or "none",
               status["calculated_ticks_per_mm"]), log=False)

    cmd_QUERY_FILAMENT_SENSOR_help = "Query the filament motion monitor"
    def cmd_QUERY_FILAMENT_SENSOR(self, gcmd):
        self._respond_status(gcmd)

    cmd_SET_FILAMENT_SENSOR_help = "Enable or disable the filament monitor"
    def cmd_SET_FILAMENT_SENSOR(self, gcmd):
        enable = gcmd.get_int("ENABLE", 1, minval=0, maxval=1)
        self._set_enabled(bool(enable))

    cmd_QUERY_FILAMENT_MONITOR_help = "Query detailed filament motion data"
    def cmd_QUERY_FILAMENT_MONITOR(self, gcmd):
        self._respond_status(gcmd)

    cmd_SET_FILAMENT_MONITOR_help = "Change runtime monitor settings"
    def cmd_SET_FILAMENT_MONITOR(self, gcmd):
        enable = gcmd.get_int("ENABLE", None, minval=0, maxval=1)
        ticks_per_mm = gcmd.get_float("TICKS_PER_MM", None, above=0.0)
        if enable is not None:
            self._set_enabled(bool(enable))
        if ticks_per_mm is not None:
            self.ticks_per_mm = ticks_per_mm
            self._reset_monitoring_baselines()
        self._respond_status(gcmd)

    def _set_enabled(self, enable):
        if enable and not self.sensor_enabled:
            self._reset_monitoring_baselines()
            self.active_fault = ""
            self.filament_present = True
            self.min_event_systime = self.reactor.monotonic() + self.event_delay
        self.sensor_enabled = enable

    cmd_RESET_FILAMENT_MONITOR_help = "Reset counters and latched faults"
    def cmd_RESET_FILAMENT_MONITOR(self, gcmd):
        now = self.reactor.monotonic()
        self._reset_counters(now)
        self.min_event_systime = now + self.event_delay
        self._respond_status(gcmd)

    cmd_CALIBRATE_FILAMENT_MONITOR_help = (
        "Report recommended ticks_per_mm from collected motion")
    def cmd_CALIBRATE_FILAMENT_MONITOR(self, gcmd):
        length = gcmd.get_float("LENGTH", None, above=0.0)
        if length is None:
            length = self.commanded_extrusion_length
        if length <= 0.0:
            raise gcmd.error(
                "No extrusion measured; supply LENGTH or extrude after RESET")
        if self.tick_count <= 0:
            raise gcmd.error("No sensor ticks measured")
        recommendation = self.tick_count / length
        gcmd.respond_info(
            ("Filament monitor %s calibration: ticks=%d length=%.3fmm\n"
             "Recommended config: ticks_per_mm: %.6f")
            % (self.name, self.tick_count, length, recommendation), log=False)


def load_config_prefix(config):
    return FilamentMotionMonitor(config)
