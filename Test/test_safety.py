'''Safety fixes in 25.10.1: the relay is switched off when the control
loop fails, crashes in profile and PID math are gone, firing time is
immune to wall-clock jumps, and a failing thermocouple read can no
longer freeze the temperature.

Ovens are built without __init__ so no hardware is touched and no
threads start; each test drives one pass of the loop by hand.'''

import json
import math
import time

import pytest

import config
import oven


class FakePin(object):
    def __init__(self):
        self.value = False


class FakeStatus(object):
    def over_error_limit(self):
        return False


class FakeSensor(object):
    def __init__(self, temp):
        self.temp = temp
        self.status = FakeStatus()

    def temperature(self):
        return self.temp


class FakeBoard(object):
    def __init__(self, temp):
        self.temp_sensor = FakeSensor(temp)


def make_output():
    '''the real Output class driving a fake pin'''
    output = oven.Output.__new__(oven.Output)
    output.active = False
    output.heater = FakePin()
    output.off = False
    output.on = True
    return output


def make_profile(data=((0, 20), (3600, 1000))):
    return oven.Profile(json.dumps({"name": "test", "data": [list(p) for p in data]}))


def make_real_oven(temp=20):
    o = oven.RealOven.__new__(oven.RealOven)
    o.board = FakeBoard(temp)
    o.output = make_output()
    o.temperature = 0
    o.time_step = 0.01
    o.reset()
    return o


def start_running(o, profile=None):
    o.profile = profile or make_profile()
    o.totaltime = o.profile.get_duration()
    o.runtime = 0
    o.start_time = time.monotonic()
    o.state = "RUNNING"


@pytest.fixture(autouse=True)
def no_state_file(monkeypatch):
    # abort_run() saves the automatic restart state; keep tests off disk
    monkeypatch.setattr(config, "automatic_restarts", False)
    monkeypatch.setattr(config, "kiln_must_catch_up", False)


# relay fail-safe

def test_control_loop_error_switches_relay_off_and_aborts():
    o = make_real_oven()
    start_running(o)

    def heat_then_fail():
        o.output.heater.value = o.output.on
        raise RuntimeError("boom")
    o.heat_then_cool = heat_then_fail

    o.run_guarded()  # must not raise: the control thread keeps going

    assert o.output.heater.value == o.output.off
    assert o.state == "IDLE"


def test_relay_off_even_if_abort_fails():
    o = make_real_oven()
    start_running(o)

    def heat_then_fail():
        o.output.heater.value = o.output.on
        raise RuntimeError("boom")
    o.heat_then_cool = heat_then_fail

    def abort_fails():
        raise RuntimeError("abort failed too")
    o.abort_run = abort_fails

    o.run_guarded()

    assert o.output.heater.value == o.output.off


def test_relay_off_respects_inverted_output():
    o = make_real_oven()
    o.output.off, o.output.on = True, False
    o.output.heater.value = o.output.on
    o.relay_off()
    assert o.output.heater.value is True


def test_nan_temperature_no_longer_leaves_relay_on():
    '''the crash seen in the rehearsal of 25.10.0: a nan reading made
    Output.heat() switch the relay on, then time.sleep(nan) raised and
    killed the control thread with the relay still on.'''
    o = make_real_oven(temp=math.nan)
    start_running(o)

    o.run_guarded()

    assert o.output.heater.value == o.output.off
    assert o.state == "IDLE"


def test_paused_without_profile_returns_to_idle():
    o = make_real_oven()
    o.state = "PAUSED"
    o.profile = None
    o.output.heater.value = o.output.on

    o.run_guarded()

    assert o.state == "IDLE"
    assert o.output.heater.value == o.output.off


# crash fixes

def test_target_temperature_exactly_at_profile_end():
    profile = make_profile()
    assert profile.get_target_temperature(3600) == 1000


def test_target_temperature_past_end_is_zero():
    assert make_profile().get_target_temperature(3601) == 0


def test_find_x_on_flat_segment_does_not_divide_by_zero():
    assert oven.Profile.find_x_given_y_on_line_from_two_points(100, (0, 100), (60, 100)) == 0


def test_pid_zero_time_delta_does_not_crash():
    pid = oven.PID(ki=30, kp=6, kd=300)
    now = time.monotonic()
    pid.lastNow = now
    out = pid.compute(100, 100 - config.pid_control_window / 2, now)
    assert 0 <= out <= 1


def test_pid_ki_zero_does_not_crash():
    pid = oven.PID(ki=0, kp=6, kd=300)
    now = pid.lastNow + 1
    out = pid.compute(100, 100 - config.pid_control_window / 2, now)
    assert 0 <= out <= 1


# timing immune to wall-clock changes

def test_runtime_ignores_wall_clock_jumps(monkeypatch):
    mono = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: mono[0])
    o = make_real_oven()
    start_running(o)

    # a daylight-saving change (or ntp sync after boot) moves the wall
    # clock by an hour while two real seconds pass
    wall = time.time()
    monkeypatch.setattr(time, "time", lambda: wall - 3600)
    mono[0] += 2
    o.update_runtime()

    assert o.runtime == pytest.approx(2)


def test_pid_time_delta_ignores_wall_clock_jumps(monkeypatch):
    pid = oven.PID(ki=30, kp=6, kd=300)
    pid.lastNow = 500.0
    wall = time.time()
    monkeypatch.setattr(time, "time", lambda: wall + 3600)
    pid.compute(100, 100 - config.pid_control_window / 2, 501.0)
    assert pid.pidstats['timeDelta'] == pytest.approx(1.0)


def test_pid_keeps_sub_second_precision():
    pid = oven.PID(ki=30, kp=6, kd=300)
    pid.lastNow = 500.0
    pid.compute(100, 100 - config.pid_control_window / 2, 500.25)
    assert pid.pidstats['timeDelta'] == pytest.approx(0.25)


# thermocouple reads

def make_sensor(raw_temp):
    sensor = oven.TempSensorReal.__new__(oven.TempSensorReal)
    sensor.status = oven.ThermocoupleTracker()
    sensor.temptracker = oven.TempTracker()
    sensor.raw_temp = raw_temp
    return sensor


def test_spi_error_counts_as_bad_read_and_does_not_raise():
    def spi_error():
        raise OSError(5, "Input/output error")
    sensor = make_sensor(spi_error)
    before = list(sensor.temptracker.temps)

    sensor.sample()  # used to kill the sensor thread

    assert sensor.status.status[-1] is False
    assert sensor.temptracker.temps == before


def test_nan_read_counts_as_bad_and_is_not_averaged():
    sensor = make_sensor(lambda: math.nan)
    before = list(sensor.temptracker.temps)
    sensor.sample()
    assert sensor.status.status[-1] is False
    assert sensor.temptracker.temps == before


def test_good_read_still_recorded(monkeypatch):
    monkeypatch.setattr(config, "temp_scale", "c")
    sensor = make_sensor(lambda: 123.0)
    sensor.sample()
    assert sensor.status.status[-1] is True
    assert sensor.temptracker.temps[-1] == 123.0


def test_repeated_read_errors_abort_the_firing():
    '''failed reads now reach the too-many-errors check, which aborts
    the run and switches the relay off'''
    def spi_error():
        raise OSError(5, "Input/output error")
    sensor = make_sensor(spi_error)
    o = make_real_oven()
    o.board.temp_sensor = sensor
    start_running(o)
    o.output.heater.value = o.output.on

    for _ in range(config.temperature_average_samples * 2):
        sensor.sample()
    o.reset_if_emergency()

    assert o.state == "IDLE"
    assert o.output.heater.value == o.output.off
