#!/usr/bin/env python3
"""zikzak controls: MQTT-exposed HA buttons that run privileged commands.

Each entry in BUTTONS becomes a Home Assistant button entity (via MQTT
discovery) under the existing `zikzak` device. Pressing the button publishes
to that button's command topic, which triggers the configured shell command.

Commands run via `sudo -n` so they must be whitelisted in
/etc/sudoers.d/zikzak-controls. The service itself runs unprivileged.

MQTT topics (per button `name`):
  zikzak/controls/<name>/press      <- command   (any payload triggers)
  zikzak/controls/available         -> "online" / "offline"  (LWT, retained)

Environment (from /etc/zikzak/controls.env):
  MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading

import paho.mqtt.client as mqtt

# (name, display, command-as-list, icon)
BUTTONS = [
    (
        "crt_wall",
        "Restart CRT Wall",
        ["sudo", "-n", "systemctl", "restart", "quadmux-display.service"],
        "mdi:television-classic",
    ),
]

TOPIC_AVAIL = "zikzak/controls/available"

log = logging.getLogger("zikzak-controls")


def cmd_topic(name: str) -> str:
    return f"zikzak/controls/{name}/press"


def discovery_topic(name: str) -> str:
    return f"homeassistant/button/zikzak_{name}/config"


def publish_discovery(client: mqtt.Client) -> None:
    for name, display, _cmd, icon in BUTTONS:
        payload = {
            "name": display,
            "unique_id": f"zikzak_{name}",
            "command_topic": cmd_topic(name),
            "availability_topic": TOPIC_AVAIL,
            "icon": icon,
            # Match audio-switcher: identifiers-only keeps device grouping
            # without the has_entity_name footguns documented there.
            "device": {"identifiers": ["zikzak"]},
        }
        client.publish(discovery_topic(name), json.dumps(payload), qos=1, retain=True)


def run_button(name: str, cmd: list[str]) -> None:
    log.info("button %s pressed; running: %s", name, " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        log.error("button %s: command timed out", name)
        return
    except Exception:
        log.exception("button %s: command failed to launch", name)
        return
    if result.returncode != 0:
        log.error(
            "button %s: rc=%s stdout=%r stderr=%r",
            name, result.returncode, result.stdout, result.stderr,
        )
    else:
        log.info("button %s: ok", name)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    host = os.environ["MQTT_HOST"]
    port = int(os.environ.get("MQTT_PORT", "1883"))
    user = os.environ["MQTT_USER"]
    password = os.environ["MQTT_PASS"]

    by_name = {name: cmd for name, _d, cmd, _i in BUTTONS}

    client = mqtt.Client(client_id="zikzak-controls", clean_session=True)
    client.username_pw_set(user, password)
    client.will_set(TOPIC_AVAIL, "offline", qos=1, retain=True)

    def on_connect(c, _userdata, _flags, rc):
        if rc != 0:
            log.error("MQTT connect failed rc=%s", rc)
            return
        log.info("MQTT connected to %s:%s", host, port)
        c.publish(TOPIC_AVAIL, "online", qos=1, retain=True)
        publish_discovery(c)
        for name, *_ in BUTTONS:
            c.subscribe(cmd_topic(name), qos=1)

    def on_message(_c, _userdata, msg):
        # Topic shape: zikzak/controls/<name>/press
        parts = msg.topic.split("/")
        if len(parts) != 4 or parts[3] != "press":
            log.warning("unexpected topic: %s", msg.topic)
            return
        name = parts[2]
        cmd = by_name.get(name)
        if cmd is None:
            log.warning("no button registered for %s", name)
            return
        threading.Thread(target=run_button, args=(name, cmd), daemon=True).start()

    client.on_connect = on_connect
    client.on_message = on_message

    shutdown = threading.Event()

    def handle_signal(_signum, _frame):
        shutdown.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    client.connect(host, port, keepalive=60)
    client.loop_start()
    try:
        shutdown.wait()
    finally:
        try:
            client.publish(TOPIC_AVAIL, "offline", qos=1, retain=True)
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
