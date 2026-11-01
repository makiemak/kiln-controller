### Slack notifications

`kiln-notify.py` sends slack messages about the kiln. It is a separate program from `kiln-controller.py`: it listens to the same `/status` websocket a browser tab uses and never sends the kiln a command, so stopping or crashing it cannot affect a firing.

It replaces `watcher.py` for monitoring, which treats an idle kiln as a failure.

#### Messages

| Level | When | Default thresholds |
| ----- | ---- | ------- |
| Info | Firing started | |
| Info | Firing finished, with peak, duration and cost | Within 15 s of the schedule's end |
| Info | Kiln cooled after a firing | 65 degrees |
| Critical | Firing ended early: the Stop button, an emergency shutoff or an error. The kiln's status doesn't say which | |
| Critical | Kiln controller not responding, followed by a message when it is back | 60 s |
| Critical | Behind the schedule and not heating: possible failed element or relay stuck open | Under 2 degrees rise in 15 min |
| Critical | Far from the target | 25 degrees for 10 min |
| Critical | Temperature rising with no firing running: possible stuck relay | 15 degrees in 5 min, ignoring the first 5 min after a firing |

Critical messages repeat every 30 minutes while the problem lasts, except "ended early", which is sent once. If slack can't be reached, messages wait in a queue and are sent when it can.

**What it can't tell you:** it runs on the Pi, so it can't report the Pi losing power or wifi. If an expected message doesn't arrive, check the kiln.

On phones, slack only pushes mentions by default, and a webhook post isn't one. So critical messages and calibration reminders include `<!channel>`, which also posts to everyone in the channel: use a channel just for the kiln. Change or blank it with `mention` in the settings file.

#### Calibration reminders

For profiles named in `reminder_profiles`, every flat segment of at least 5 minutes gets two reminders: "get ready" 10 minutes before it starts, and "read the front thermometer now" 5 minutes before it ends, with the web reading at that moment. They follow the schedule's clock, so they move with it if the kiln falls behind.

#### Setup

1. In slack, create a channel and add an [incoming webhook](https://slack.com/help/articles/115005265063-Incoming-webhooks-for-Slack) to it.
2. On the Pi, create the settings file. It stays out of git because the webhook url is a secret:

        $ cp ~/kiln-controller/kiln-notify.conf.example ~/kiln-notify.conf
        $ chmod 600 ~/kiln-notify.conf
        $ nano ~/kiln-notify.conf

3. Send a test message:

        $ ~/kiln-controller/venv/bin/python ~/kiln-controller/kiln-notify.py --test

4. Optionally, send one of every message, marked as simulated, to check how they look and sound on your phone. It takes about 2 minutes and doesn't touch the kiln:

        $ ~/kiln-controller/venv/bin/python ~/kiln-controller/kiln-notify.py --demo

5. Install and start the service:

        $ sudo cp ~/kiln-controller/lib/init/kiln-notify.service /etc/systemd/system/
        $ sudo systemctl daemon-reload
        $ sudo systemctl enable --now kiln-notify

Its log is at `journalctl -u kiln-notify`. Stopping it with `sudo systemctl stop kiln-notify` has no effect on the kiln.
