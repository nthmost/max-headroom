#!/usr/bin/env python3
"""zikzak-thermals: publishes CPU + GPU temps to HA via MQTT discovery.

Polls every POLL_INTERVAL seconds and publishes as temperature sensors
joined to the existing `zikzak` HA device.

MQTT topics:
  zikzak/thermals/<slug>/state      -> current °C value
  zikzak/thermals/available         -> "online" / "offline"  (LWT, retained)

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

POLL_INTERVAL = 30  # seconds

TOPIC_AVAIL = "zikzak/thermals/available"

# (slug, display_name, icon)
SENSORS = [
    ("cpu_package", "CPU Package Temp", "mdi:thermometer"),
    ("gpu0_temp", "GPU 0 Temp (GTX 1080)", "mdi:expansion-card"),
    ("gpu1_temp", "GPU 1 Temp (GTX 1060)", "mdi:expansion-card"),
]

log = logging.getLogger("zikzak-thermals")


def state_topic(slug: str) -> str:
    return f"zikzak/thermals/{slug}/state"


def discovery_topic(slug: str) -> str:
    return f"homeassistant/sensor/zikzak_{slug}/config"


def publish_discovery(client: mqtt.Client) -> None:
    for slug, display, icon in SENSORS:
        payload = {
            "name": display,
            "unique_id": f"zikzak_{slug}",
            "state_topic": state_topic(slug),
            "availability_topic": TOPIC_AVAIL,
            "device_class": "temperature",
            "unit_of_measurement": "°C",
            "icon": icon,
            "device": {"identifiers": ["zikzak"]},
        }
        client.publish(discovery_topic(slug), json.dumps(payload), qos=1, retain=True)


def read_cpu_package_temp() -> float | None:
    try:
        out = subprocess.check_output(["sensors", "-j"], text=True, timeout=5,
                                      stderr=subprocess.DEVNULL)
        data = json.loads(out)
        chip = data.get("coretemp-isa-0000", {})
        pkg = chip.get("Package id 0", {})
        for key, val in pkg.items():
            if key.endswith("_input"):
                return float(val)
    except Exception as e:
        log.warning("cpu temp read failed: %s", e)
    return None


def read_gpu_temps() -> tuple[float | None, float | None]:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
            text=True, timeout=5,
        )
        lines = [ln.strip() for ln in out.strip().splitlines() if ln.strip()]
        gpu0 = float(lines[0]) if len(lines) > 0 else None
        gpu1 = float(lines[1]) if len(lines) > 1 else None
        return gpu0, gpu1
    except Exception as e:
        log.warning("gpu temp read failed: %s", e)
        return None, None


def publish_state(client: mqtt.Client) -> None:
    cpu = read_cpu_package_temp()
    gpu0, gpu1 = read_gpu_temps()

    for slug, val in [("cpu_package", cpu), ("gpu0_temp", gpu0), ("gpu1_temp", gpu1)]:
        if val is not None:
            client.publish(state_topic(slug), str(val), qos=0, retain=False)

    log.info("published: cpu=%.1f°C  gpu0=%s°C  gpu1=%s°C",
             cpu or -1, gpu0, gpu1)


def poll_loop(client: mqtt.Client, stop_evt: threading.Event) -> None:
    while not stop_evt.wait(POLL_INTERVAL):
        publish_state(client)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    host = os.environ["MQTT_HOST"]
    port = int(os.environ.get("MQTT_PORT", 1883))
    user = os.environ.get("MQTT_USER")
    passwd = os.environ.get("MQTT_PASS")

    client = mqtt.Client(client_id="zikzak-thermals", clean_session=True)
    if user:
        client.username_pw_set(user, passwd)
    client.will_set(TOPIC_AVAIL, "offline", qos=1, retain=True)

    stop_evt = threading.Event()

    def on_connect(c: mqtt.Client, userdata, flags, rc: int) -> None:
        if rc == 0:
            log.info("connected to MQTT broker %s:%s", host, port)
            c.publish(TOPIC_AVAIL, "online", qos=1, retain=True)
            publish_discovery(c)
            publish_state(c)
        else:
            log.error("MQTT connect failed rc=%s", rc)

    client.on_connect = on_connect
    client.connect(host, port, keepalive=60)

    poll_thread = threading.Thread(target=poll_loop, args=(client, stop_evt), daemon=True)
    poll_thread.start()

    def shutdown(sig, frame) -> None:
        log.info("shutting down")
        stop_evt.set()
        client.publish(TOPIC_AVAIL, "offline", qos=1, retain=True)
        client.loop_stop()
        client.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    client.loop_forever()


if __name__ == "__main__":
    main()
