'''kiln-notify decides what to send from a stream of kiln states. These
tests feed it states on a fake clock, with no network or kiln.'''

import datetime
import importlib.util
import os
import re

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
spec = importlib.util.spec_from_file_location("kiln_notify", os.path.join(ROOT, "kiln-notify.py"))
kiln_notify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kiln_notify)

STEPS = [[0, 25], [1800, 200], [3000, 200], [4800, 400], [6000, 400], [7800, 600], [9000, 600]]


def settings(**overrides):
    s = {}
    for key, value in kiln_notify.DEFAULTS.items():
        if key in kiln_notify.STRING_SETTINGS:
            s[key] = value
        elif key == "reminder_profiles":
            s[key] = ["calibrate-steps"]
        else:
            s[key] = float(value)
    s.update(overrides)
    return s


class Clock(object):
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Rig(object):
    def __init__(self, **overrides):
        self.clock = Clock()
        self.sent = []
        self.n = kiln_notify.Notifier(settings(**overrides), self.sent.append,
                                      lambda name: STEPS, clock=self.clock)

    def state(self, state="IDLE", temp=20.0, target=0, runtime=0, total=0,
              profile=None, catching_up=False):
        return {"state": state, "temperature": temp, "target": target, "runtime": runtime,
                "totaltime": total, "profile": profile, "catching_up": catching_up,
                "cost": 0.14, "currency_type": "$"}

    def feed(self, seconds=1, **kwargs):
        '''feed the same state, one message per second'''
        for _ in range(int(seconds)):
            self.n.update(self.state(**kwargs))
            self.n.tick()
            self.clock.now += 1

    def firing(self, seconds=1, temp=100.0, target=100.0, runtime=60, total=1200, **kwargs):
        self.feed(seconds, state="RUNNING", temp=temp, target=target, runtime=runtime,
                  total=total, profile="test", **kwargs)

    def named(self, word):
        return [m for m in self.sent if word in m]


def test_idle_kiln_says_nothing():
    rig = Rig()
    rig.feed(3600)
    assert rig.sent == []


def test_firing_started_and_finished():
    rig = Rig()
    rig.feed(5)
    rig.firing(5, runtime=0)
    rig.firing(5, temp=108.6, runtime=1195)
    rig.feed(5, temp=100)
    assert len(rig.named("Firing started")) == 1
    finished = rig.named("Firing finished")
    assert len(finished) == 1
    assert "108.6" in finished[0] and "$0.14" in finished[0]
    assert rig.named("KILN ALERT") == []


def test_ended_early_is_critical_and_sent_once():
    rig = Rig()
    rig.feed(5)
    rig.firing(5, runtime=300)
    rig.feed(3600, temp=100)
    assert len(rig.named("ended early")) == 1


def test_paused_and_resumed_is_not_a_new_firing():
    rig = Rig()
    rig.feed(5)
    rig.firing(5)
    rig.feed(5, state="PAUSED", temp=100, target=100, runtime=60, total=1200, profile="test")
    rig.firing(5)
    assert len(rig.named("Firing started")) == 1
    assert rig.named("KILN ALERT") == []


def test_cooled_message_once_below_threshold():
    rig = Rig()
    rig.feed(5)
    rig.firing(5, runtime=1195)
    rig.feed(5, temp=100)
    rig.feed(5, temp=65)
    rig.feed(5, temp=60)
    assert len(rig.named("cooled")) == 1


def test_unreachable_alert_repeats_and_recovers():
    rig = Rig()
    rig.firing(5, runtime=60)
    rig.clock.now += 61
    rig.n.tick()
    alerts = rig.named("not responding")
    assert len(alerts) == 1 and "check it now" in alerts[0]
    rig.clock.now += 60
    rig.n.tick()
    assert len(rig.named("not responding")) == 1
    rig.clock.now += 30 * 60
    rig.n.tick()
    assert len(rig.named("not responding")) == 2
    rig.firing(1, runtime=60)
    assert len(rig.named("is back")) == 1


def test_short_restart_of_the_kiln_is_not_unreachable():
    rig = Rig()
    rig.feed(5)
    rig.clock.now += 30
    rig.n.tick()
    assert rig.named("not responding") == []


def test_stalled_while_catching_up():
    rig = Rig()
    rig.feed(5)
    rig.firing(16 * 60, temp=500.0, target=515.0, catching_up=True)
    assert len(rig.named("isn't heating")) == 1


def test_catching_up_but_rising_is_fine():
    rig = Rig()
    rig.feed(5)
    for minute in range(40):
        rig.firing(60, temp=500.0 + minute, target=515.0 + minute, catching_up=True)
    assert rig.named("KILN ALERT") == []


def test_far_above_target():
    rig = Rig()
    rig.feed(5)
    rig.firing(11 * 60, temp=130.0, target=100.0, catching_up=True)
    assert len(rig.named("for over 10 min")) == 1


def test_overshoot_from_the_sanity_run_is_not_an_alert():
    rig = Rig()
    rig.feed(5)
    rig.firing(5 * 60, temp=109.6, target=100.0, catching_up=False)
    assert rig.named("KILN ALERT") == []


def test_rising_while_idle():
    rig = Rig()
    for second in range(300):
        rig.feed(1, temp=20.0 + second / 15)
    assert len(rig.named("relay may be stuck")) == 1


def test_heat_soak_just_after_a_firing_is_ignored():
    rig = Rig()
    rig.feed(5)
    rig.firing(5, runtime=300)
    for second in range(240):
        rig.feed(1, temp=100.0 + second / 12)
    assert rig.named("relay may be stuck") == []


def test_find_holds():
    assert kiln_notify.find_holds(STEPS, 300) == [
        (1800, 3000, 200), (4800, 6000, 400), (7800, 9000, 600)]
    assert kiln_notify.find_holds([[0, 25], [100, 100], [200, 100]], 300) == []


def calibrate(rig, runtime, temp=200.0, target=200.0, seconds=1):
    rig.feed(seconds, state="RUNNING", temp=temp, target=target, runtime=runtime,
             total=9000, profile="calibrate-steps")


def test_reminders_follow_the_schedule():
    rig = Rig()
    rig.feed(5)
    calibrate(rig, 0)
    assert "6 reminders" in rig.named("Firing started")[0]
    calibrate(rig, 1199)
    assert rig.named("Get ready") == []
    calibrate(rig, 1200, seconds=5)
    assert len(rig.named("Get ready")) == 1
    # the kiln fell behind, so the schedule waits; the clock moving on
    # must not bring the reminder forward
    calibrate(rig, 2600, seconds=3600)
    assert rig.named("Read the front thermometer") == []
    calibrate(rig, 2700, temp=199.8, seconds=5)
    reads = rig.named("Read the front thermometer")
    assert len(reads) == 1
    assert "199.8" in reads[0] and "200.0" in reads[0]


def test_clock_time_is_12_hour():
    def at(hour, minute):
        return datetime.datetime(2026, 11, 1, hour, minute)
    assert kiln_notify.clock_time(at(15, 40)) == "3:40 PM"
    assert kiln_notify.clock_time(at(9, 5)) == "9:05 AM"
    assert kiln_notify.clock_time(at(0, 5)) == "12:05 AM"
    assert kiln_notify.clock_time(at(12, 0)) == "12:00 PM"


def test_reminders_show_12_hour_time():
    rig = Rig()
    rig.feed(5)
    calibrate(rig, 0)
    calibrate(rig, 1200)
    calibrate(rig, 2700)
    clock = re.compile(r"\b\d{1,2}:\d\d [AP]M\b")
    assert clock.search(rig.named("Get ready")[0])
    assert clock.search(rig.named("Read the front thermometer")[0])


def test_every_hold_gets_both_reminders():
    rig = Rig()
    rig.feed(5)
    for runtime in range(0, 9000, 30):
        calibrate(rig, runtime)
    assert len(rig.named("Get ready")) == 3
    assert len(rig.named("Read the front thermometer")) == 3


def test_other_profiles_get_no_reminders():
    rig = Rig()
    rig.feed(5)
    rig.firing(5, runtime=0)
    rig.firing(5, runtime=2700)
    assert rig.named("Get ready") == [] and rig.named("Read the front") == []


def test_restart_during_a_firing_does_not_replay_reminders():
    rig = Rig()
    calibrate(rig, 2800)
    assert rig.named("Firing started") == []
    assert "started during a firing" in rig.sent[0]
    assert "3 reminders" in rig.sent[0] or "4 reminders" in rig.sent[0]
    assert rig.named("Get ready") == [] and rig.named("Read the front") == []


def test_sender_keeps_messages_until_slack_answers(monkeypatch):
    requests = pytest.importorskip("requests")
    posted = []
    up = [False]

    class Ok(object):
        def raise_for_status(self):
            pass

    def post(url, json, timeout):
        if not up[0]:
            raise requests.exceptions.ConnectionError("down")
        posted.append(json["text"])
        return Ok()
    monkeypatch.setattr(requests, "post", post)

    clock = Clock()
    sender = kiln_notify.SlackSender("https://example.invalid/hook", clock=clock)
    sender.send("one")
    sender.send("two")
    assert sender.flush() is False
    clock.now += 31
    up[0] = True
    assert sender.flush() is True
    assert posted == ["one", "two"]


def test_attention_messages_mention_the_channel():
    rig = Rig()
    rig.feed(5)
    rig.firing(5, runtime=300)
    rig.feed(1)
    assert rig.named("ended early")[0].startswith("<!channel>")
    assert "<!channel>" not in rig.named("Firing started")[0]


def test_demo_covers_every_message():
    messages = kiln_notify.demo_messages(settings())
    text = "\n".join(messages)
    for word in ("Firing started", "Get ready", "Read the front thermometer",
                 "Firing finished", "cooled", "ended early", "not responding",
                 "is back", "isn't heating", "for over 10 min", "relay may be stuck"):
        assert word in text, word


def test_load_settings(tmp_path):
    conf = tmp_path / "kiln-notify.conf"
    conf.write_text("[notify]\nwebhook_url = https://example.invalid/hook\n"
                    "reminder_profiles = a, b\ncooled_temp = 50\n")
    s = kiln_notify.load_settings(str(conf))
    assert s["webhook_url"] == "https://example.invalid/hook"
    assert s["reminder_profiles"] == ["a", "b"]
    assert s["cooled_temp"] == 50.0
    assert s["repeat_minutes"] == 30.0
