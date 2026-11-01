#!/usr/bin/env python
'''Sends slack messages about the kiln: firings starting and ending,
problems, and reminders during a calibration firing.

This is a separate program, not part of the kiln controller. It listens
to the same /status websocket a browser tab uses and never sends the
kiln a command, so stopping or crashing it cannot affect a firing.

Settings live in ~/kiln-notify.conf, which is not in git because the
webhook url is a secret. See docs/notifications.md.

    kiln-notify.py          run forever
    kiln-notify.py --test   send one test message and exit
    kiln-notify.py --demo   send one of every message, marked simulated
'''

import argparse
import collections
import configparser
import datetime
import json
import logging
import os
import sys
import time

log = logging.getLogger("kiln-notify")

DEFAULTS = {
    "status_url": "ws://localhost:8081/status",
    "storage_url": "ws://localhost:8081/storage",
    "temp_unit": "C",
    # added to messages that need attention. slack only pushes mentions
    # to phones by default, and a webhook post isn't one without this.
    "mention": "<!channel>",
    # kiln unreachable for this long
    "unreachable_seconds": "60",
    # catching up but less than this rise over this many minutes
    "stall_rise": "2",
    "stall_minutes": "15",
    # this far from target for this many minutes
    "off_target": "25",
    "off_target_minutes": "10",
    # rising this much in this many minutes while idle: relay stuck on.
    # ignored just after a firing, while the kiln's heat evens out.
    "idle_rise": "15",
    "idle_rise_minutes": "5",
    "idle_grace_minutes": "5",
    # a firing ending this close to the schedule's end finished normally
    "finish_margin_seconds": "15",
    # safe to open below this
    "cooled_temp": "65",
    # repeat a critical alert this often while the problem lasts
    "repeat_minutes": "30",
    # comma separated profile names that get hold reminders
    "reminder_profiles": "",
    # a flat segment at least this long is a hold
    "hold_minutes": "5",
    # say get ready this long before a hold starts
    "prepare_minutes": "10",
    # say read now this long before a hold ends
    "read_before_end_minutes": "5",
}


STRING_SETTINGS = ("status_url", "storage_url", "temp_unit", "mention")


def load_settings(path):
    '''returns a dict of settings from the conf file, over the defaults.'''
    parser = configparser.ConfigParser(defaults=DEFAULTS, interpolation=None)
    if not parser.read(path):
        raise SystemExit("cannot read %s, see docs/notifications.md" % path)
    section = parser["notify"] if parser.has_section("notify") else parser["DEFAULT"]
    settings = {}
    for key, default in DEFAULTS.items():
        value = section.get(key)
        if key in STRING_SETTINGS:
            settings[key] = value
        elif key == "reminder_profiles":
            settings[key] = [n.strip() for n in value.split(",") if n.strip()]
        else:
            settings[key] = float(value)
    settings["webhook_url"] = section.get("webhook_url", "").strip()
    return settings


def find_holds(data, min_seconds):
    '''returns (start, end, temperature) for each flat stretch of a
    profile's [seconds, temperature] points lasting at least min_seconds.'''
    holds = []
    points = sorted(data)
    for (t1, temp1), (t2, temp2) in zip(points, points[1:]):
        if temp1 == temp2 and t2 - t1 >= min_seconds:
            holds.append((t1, t2, temp1))
    return holds


class Notifier(object):
    '''Decides what to send, from the stream of kiln states. It has no
    network or clock of its own so it can be tested with recorded data:
        update(msg)  a state message from the kiln
        tick()       call regularly, messages arriving or not
    send(text) delivers a message, clock() returns seconds, and
    get_profile(name) returns a profile's points, or None.'''

    def __init__(self, settings, send, get_profile, clock=time.monotonic):
        self.s = settings
        self.send = send
        self.get_profile = get_profile
        self.clock = clock
        self.last = None            # last state message
        self.last_seen = clock()
        self.unreachable = False
        self.sent = {}              # critical alert name -> time last sent
        self.temps = collections.deque()  # (time, temp) while idle
        self.ended_at = None
        self.waiting_to_cool = False
        self.reset_firing()

    def reset_firing(self):
        self.peak = 0
        self.started_at = None
        self.stall_from = None
        self.off_target_since = None
        self.reminders = []

    def fmt(self, temp):
        return "%.1f °%s" % (temp, self.s["temp_unit"])

    def info(self, text):
        log.info(text)
        self.send(text)

    def critical(self, name, text):
        '''send now, then every repeat_minutes while it stays active.'''
        now = self.clock()
        last = self.sent.get(name)
        if last is None or now - last >= self.s["repeat_minutes"] * 60:
            self.sent[name] = now
            log.error(text)
            self.send("%s :rotating_light: *KILN ALERT* %s" % (self.s["mention"], text))

    def clear(self, name):
        self.sent.pop(name, None)

    def update(self, msg):
        state = msg["state"]
        now = self.clock()
        self.last_seen = now
        if self.unreachable:
            self.unreachable = False
            self.clear("unreachable")
            self.info(":white_check_mark: Kiln controller is back: %s, %s"
                      % (state, self.fmt(msg["temperature"])))

        firing = state in ("RUNNING", "PAUSED")
        was_firing = self.last is not None and self.last["state"] in ("RUNNING", "PAUSED")
        if firing and not was_firing:
            self.firing_started(msg)
        if was_firing and not firing:
            self.firing_ended(now)

        if firing:
            self.peak = max(self.peak, msg["temperature"])
            self.temps.clear()
            if state == "RUNNING":
                self.check_stalled(msg, now)
                self.check_off_target(msg, now)
                self.check_reminders(msg)
        else:
            self.check_idle(msg, now)

        self.last = msg

    def tick(self):
        silent = self.clock() - self.last_seen
        if silent >= self.s["unreachable_seconds"]:
            self.unreachable = True
            if self.last is None:
                where = "No state received since the notifier started."
            else:
                where = "Last seen %s at %s." % (self.last["state"],
                                                 self.fmt(self.last["temperature"]))
            firing = self.last is not None and self.last["state"] == "RUNNING"
            self.critical("unreachable",
                          "Kiln controller not responding for %d s. %s%s"
                          % (silent, where,
                             " The kiln may be firing unattended, check it now." if firing else ""))

    def firing_started(self, msg):
        self.reset_firing()
        self.started_at = self.clock()
        self.waiting_to_cool = False
        name = msg.get("profile")
        if self.last is None:
            # the notifier restarted, the firing didn't
            text = ":eyes: Notifier started during a firing: *%s*, now %s" % (
                name, self.fmt(msg["temperature"]))
        else:
            text = ":fire: Firing started: *%s*, at %s" % (name, self.fmt(msg["temperature"]))
        if name in self.s["reminder_profiles"]:
            # anything already past is dropped, not sent in a burst
            self.reminders = [r for r in self.make_reminders(name) if r[0] > msg["runtime"]]
            text += ". %d reminders set." % len(self.reminders)
        self.info(text)

    def make_reminders(self, name):
        '''returns (runtime, kind, hold) in time order. these follow the
        schedule's clock, which waits whenever the kiln falls behind, so
        they stay right even if the firing runs late.'''
        data = self.get_profile(name)
        if not data:
            log.error("no points for profile %s, reminders off" % name)
            return []
        reminders = []
        for hold in find_holds(data, self.s["hold_minutes"] * 60):
            start, end, temp = hold
            reminders.append((start - self.s["prepare_minutes"] * 60, "prepare", hold))
            reminders.append((end - self.s["read_before_end_minutes"] * 60, "read", hold))
        return sorted(reminders, key=lambda r: r[0])

    def check_reminders(self, msg):
        while self.reminders and msg["runtime"] >= self.reminders[0][0]:
            runtime, kind, (start, end, temp) = self.reminders.pop(0)
            if kind == "prepare":
                read_at = datetime.datetime.now() + datetime.timedelta(
                    seconds=end - self.s["read_before_end_minutes"] * 60 - msg["runtime"])
                self.info("%s :alarm_clock: Get ready: the %s hold starts soon. "
                          "Reading due about %s; I'll message you."
                          % (self.s["mention"], self.fmt(temp), read_at.strftime("%H:%M")))
            else:
                self.info("%s :memo: *Read the front thermometer now* (%s hold). "
                          "Web shows %s, target %s. Time %s."
                          % (self.s["mention"], self.fmt(temp), self.fmt(msg["temperature"]),
                             self.fmt(msg["target"]),
                             datetime.datetime.now().strftime("%H:%M")))

    def firing_ended(self, now):
        last = self.last
        minutes = last["runtime"] / 60
        if last["totaltime"] - last["runtime"] <= self.s["finish_margin_seconds"]:
            self.info(":white_check_mark: Firing finished: *%s*. Peak %s, %.0f min, cost %s%.2f."
                      % (last.get("profile"), self.fmt(self.peak), minutes,
                         last.get("currency_type", ""), last.get("cost", 0)))
        else:
            self.critical("ended-early",
                          "Firing *%s* ended early, at minute %.0f of %.0f and %s. "
                          "That's the Stop button, an emergency shutoff or an error. "
                          "If you didn't press Stop, check the kiln."
                          % (last.get("profile"), minutes, last["totaltime"] / 60,
                             self.fmt(last["temperature"])))
            self.clear("ended-early")
        self.reset_firing()
        self.clear("stalled")
        self.clear("off-target")
        self.ended_at = now
        self.waiting_to_cool = True

    def check_stalled(self, msg, now):
        '''behind the schedule and not getting any hotter.'''
        temp = msg["temperature"]
        behind = msg.get("catching_up") and temp < msg["target"]
        if not behind or (self.stall_from and temp - self.stall_from[1] >= self.s["stall_rise"]):
            self.stall_from = (now, temp) if behind else None
            self.clear("stalled")
            return
        if self.stall_from is None:
            self.stall_from = (now, temp)
        if now - self.stall_from[0] >= self.s["stall_minutes"] * 60:
            self.critical("stalled",
                          "Kiln isn't heating: %s, target %s, risen under %s in %.0f min. "
                          "Possible failed element or relay stuck open."
                          % (self.fmt(temp), self.fmt(msg["target"]),
                             self.fmt(self.s["stall_rise"]), (now - self.stall_from[0]) / 60))

    def check_off_target(self, msg, now):
        error = msg["temperature"] - msg["target"]
        # below target while catching up is normal, and check_stalled
        # watches it. above target is never expected this far out.
        off = error > self.s["off_target"] or \
            (error < -self.s["off_target"] and not msg.get("catching_up"))
        if not off:
            self.off_target_since = None
            self.clear("off-target")
            return
        if self.off_target_since is None:
            self.off_target_since = now
        if now - self.off_target_since >= self.s["off_target_minutes"] * 60:
            self.critical("off-target", "Kiln is %s, target %s, for over %.0f min."
                          % (self.fmt(msg["temperature"]), self.fmt(msg["target"]),
                             self.s["off_target_minutes"]))

    def check_idle(self, msg, now):
        temp = msg["temperature"]
        if self.waiting_to_cool and temp <= self.s["cooled_temp"]:
            self.waiting_to_cool = False
            self.info(":white_check_mark: Kiln has cooled to %s." % self.fmt(temp))

        window = self.s["idle_rise_minutes"] * 60
        self.temps.append((now, temp))
        while self.temps and now - self.temps[0][0] > window:
            self.temps.popleft()
        settling = self.ended_at is not None and \
            now - self.ended_at < self.s["idle_grace_minutes"] * 60
        rise = temp - min(t for (_, t) in self.temps)
        if rise >= self.s["idle_rise"] and not settling:
            self.critical("idle-rise",
                          "Temperature rising with no firing running: up %s in %.0f min, now %s. "
                          "The relay may be stuck on. *Switch the kiln off at the wall.*"
                          % (self.fmt(rise), self.s["idle_rise_minutes"], self.fmt(temp)))
        elif rise < self.s["idle_rise"] / 2:
            self.clear("idle-rise")


class SlackSender(object):
    '''posts to a slack incoming webhook. messages wait in a queue, so a
    wifi dropout delays an alert rather than losing it.'''

    def __init__(self, url, retry_seconds=30, clock=time.monotonic):
        self.url = url
        self.retry_seconds = retry_seconds
        self.clock = clock
        self.queue = collections.deque(maxlen=100)
        self.retry_at = 0

    def send(self, text):
        self.queue.append(text)

    def flush(self):
        '''returns True when the queue is empty.'''
        import requests
        if self.clock() < self.retry_at:
            return False
        while self.queue:
            try:
                r = requests.post(self.url, json={"text": self.queue[0]}, timeout=10)
                r.raise_for_status()
            except Exception as e:
                # the exception text can include the url, which is a secret
                log.error("could not reach slack (%s), will retry" % type(e).__name__)
                self.retry_at = self.clock() + self.retry_seconds
                return False
            self.queue.popleft()
        return True


def demo_messages(settings):
    '''runs a made-up firing through the real Notifier and returns what
    it would send, so the demo can't drift from the real wording.'''
    settings = dict(settings, reminder_profiles=["demo"])
    clock = [0.0]
    sent = []
    notifier = Notifier(settings, sent.append, lambda name: [[0, 25], [1800, 200], [3000, 200]],
                        clock=lambda: clock[0])

    def feed(state="IDLE", temp=20.0, target=0, runtime=0, catching_up=False, profile="demo"):
        clock[0] += 1
        notifier.update({"state": state, "temperature": temp, "target": target,
                         "runtime": runtime, "totaltime": 3000, "profile": profile,
                         "catching_up": catching_up, "cost": 0.42, "currency_type": "$"})

    def wait(minutes):
        clock[0] += minutes * 60

    # a normal firing with reminders
    feed()
    feed("RUNNING", 22, 25)
    feed("RUNNING", 150, 142, 1200)
    feed("RUNNING", 199.8, 200, 2700)
    feed("RUNNING", 201.3, 200, 2999)
    feed(temp=198)
    feed(temp=60)

    # the problems, each on its own
    wait(60)
    feed("RUNNING", 400, 400, 900, profile="demo-firing")
    feed(temp=400)
    wait(10)
    feed(temp=350)
    wait(2)
    notifier.tick()
    feed(temp=349)
    feed("RUNNING", 500, 515, 900, catching_up=True, profile="demo-firing")
    wait(16)
    feed("RUNNING", 500.5, 515, 900, catching_up=True, profile="demo-firing")
    feed("RUNNING", 545, 515, 900, profile="demo-firing")
    wait(11)
    feed("RUNNING", 545, 515, 900, profile="demo-firing")
    feed("RUNNING", 540, 540, 2999, profile="demo-firing")
    feed(temp=538)
    wait(6)
    feed(temp=100)
    wait(4)
    feed(temp=118)
    # the scenes above each start and end a firing; one of each is enough
    return [m for m in sent if not ("started: *demo-firing*" in m or
                                    "finished: *demo-firing*" in m)]


def demo(settings, sender, delay):
    '''sends one of every message, marked as simulated.'''
    messages = demo_messages(settings)
    for number, text in enumerate(messages, 1):
        print("%d/%d %s" % (number, len(messages), text))
        sender.send("*SIMULATED, not a real kiln event.* %s" % text)
        if not sender.flush():
            return False
        time.sleep(delay)
    return True


def fetch_profile(settings, name):
    '''returns a profile's points from the kiln, or None.'''
    import websocket
    try:
        ws = websocket.create_connection(settings["storage_url"], timeout=10)
        try:
            ws.send("GET")
            for profile in json.loads(ws.recv()):
                if profile.get("name") == name:
                    return profile.get("data")
        finally:
            ws.close()
    except Exception as e:
        log.error("could not fetch profile %s: %s" % (name, e))
    return None


def run(settings, sender):
    import websocket
    notifier = Notifier(settings, sender.send,
                        lambda name: fetch_profile(settings, name))
    log.info("watching %s" % settings["status_url"])
    while True:
        try:
            ws = websocket.create_connection(settings["status_url"], timeout=5)
        except Exception as e:
            log.info("cannot connect yet: %s" % e)
            notifier.tick()
            sender.flush()
            time.sleep(5)
            continue
        try:
            while True:
                try:
                    raw = ws.recv()
                    if not raw:
                        break
                    msg = json.loads(raw)
                    if "state" in msg:
                        notifier.update(msg)
                except websocket.WebSocketTimeoutException:
                    pass
                notifier.tick()
                sender.flush()
        except Exception as e:
            log.error("lost the kiln connection: %s" % e)
        finally:
            ws.close()
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="slack messages about the kiln")
    parser.add_argument("--conf", default=os.environ.get(
        "KILN_NOTIFY_CONF", os.path.expanduser("~/kiln-notify.conf")))
    parser.add_argument("--test", action="store_true", help="send a test message and exit")
    parser.add_argument("--demo", action="store_true",
                        help="send one of every message, marked simulated, and exit")
    parser.add_argument("--demo-delay", type=float, default=8,
                        help="seconds between demo messages")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    # requests logs urls at debug level; keep the webhook out of the logs
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    settings = load_settings(args.conf)
    if not settings["webhook_url"]:
        raise SystemExit("no webhook_url in %s" % args.conf)
    sender = SlackSender(settings["webhook_url"])

    if args.test:
        sender.send(":wave: Test message from kiln-notify.")
        sys.exit(0 if sender.flush() else 1)
    if args.demo:
        sys.exit(0 if demo(settings, sender, args.demo_delay) else 1)
    run(settings, sender)


if __name__ == "__main__":
    main()
