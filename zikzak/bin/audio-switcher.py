#!/usr/bin/env python3
"""zikzak audio switcher: MQTT-controlled mpv playing one of several streams.

Listens on MQTT for a source name (ch1, knob, ...), tells a long-running mpv
to swap streams via its IPC socket. Publishes the active source as state so
Home Assistant can render it as a select entity.

MQTT topics:
  zikzak/audio/source/set     <- command  (payload: ch1 | knob)
  zikzak/audio/source         -> state    (retained)
  zikzak/audio/available      -> "online" / "offline"  (LWT, retained)

Environment (from /etc/zikzak/audio-switcher.env):
  MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS
  AUDIO_DEVICE      (default: alsa/plughw:0,0)
  MPV_SOCKET        (default: /run/zikzak-audio/mpv.sock)
  DEFAULT_SOURCE    (default: ch1)
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

SOURCES = {
    "ch1": "http://localhost:8000/ch1.ts",
    "knob": "http://10.21.1.44:8000/stream.ogg",
}

TOPIC_CMD = "zikzak/audio/source/set"
TOPIC_STATE = "zikzak/audio/source"
TOPIC_AVAIL = "zikzak/audio/available"
DISCOVERY_TOPIC = "homeassistant/select/zikzak_audio/config"

log = logging.getLogger("zikzak-audio")


class MpvController:
    def __init__(self, socket_path: Path, audio_device: str):
        self.socket_path = socket_path
        self.audio_device = audio_device
        self.proc: subprocess.Popen | None = None

    def start(self, initial_url: str) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.proc = subprocess.Popen(
            [
                "/usr/bin/mpv",
                "--no-video",
                "--ao=alsa",
                f"--audio-device={self.audio_device}",
                "--volume=100",
                "--idle=yes",
                "--force-seekable=no",
                "--cache=yes",
                "--demuxer-max-bytes=512KiB",
                "--stream-lavf-o=reconnect=1,reconnect_streamed=1,reconnect_delay_max=30",
                f"--input-ipc-server={self.socket_path}",
                initial_url,
            ]
        )
        # Wait for the IPC socket to appear.
        for _ in range(50):
            if self.socket_path.exists():
                return
            time.sleep(0.1)
        log.warning("mpv IPC socket did not appear at %s", self.socket_path)

    def send(self, command: list) -> None:
        msg = (json.dumps({"command": command}) + "\n").encode()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(str(self.socket_path))
            s.sendall(msg)

    def loadfile(self, url: str) -> None:
        self.send(["loadfile", url, "replace"])

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def publish_discovery(client: mqtt.Client) -> None:
    payload = {
        "name": "Zikzak Audio",
        "unique_id": "zikzak_audio_source",
        "command_topic": TOPIC_CMD,
        "state_topic": TOPIC_STATE,
        "availability_topic": TOPIC_AVAIL,
        "options": list(SOURCES.keys()),
        "icon": "mdi:speaker",
        "device": {
            "identifiers": ["zikzak"],
            "name": "zikzak",
            "model": "MHBN streaming server",
        },
    }
    client.publish(DISCOVERY_TOPIC, json.dumps(payload), qos=1, retain=True)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    host = os.environ["MQTT_HOST"]
    port = int(os.environ.get("MQTT_PORT", "1883"))
    user = os.environ["MQTT_USER"]
    password = os.environ["MQTT_PASS"]
    audio_device = os.environ.get("AUDIO_DEVICE", "alsa/plughw:0,0")
    socket_path = Path(os.environ.get("MPV_SOCKET", "/run/zikzak-audio/mpv.sock"))
    default_source = os.environ.get("DEFAULT_SOURCE", "ch1")

    if default_source not in SOURCES:
        log.error("DEFAULT_SOURCE=%s not in %s", default_source, list(SOURCES))
        return 2

    mpv = MpvController(socket_path, audio_device)
    mpv.start(SOURCES[default_source])
    current = {"source": default_source}

    client = mqtt.Client(client_id="zikzak-audio", clean_session=True)
    client.username_pw_set(user, password)
    client.will_set(TOPIC_AVAIL, "offline", qos=1, retain=True)

    def on_connect(c, _userdata, _flags, rc):
        if rc != 0:
            log.error("MQTT connect failed rc=%s", rc)
            return
        log.info("MQTT connected to %s:%s", host, port)
        c.publish(TOPIC_AVAIL, "online", qos=1, retain=True)
        publish_discovery(c)
        c.publish(TOPIC_STATE, current["source"], qos=1, retain=True)
        c.subscribe(TOPIC_CMD, qos=1)

    def on_message(c, _userdata, msg):
        payload = msg.payload.decode(errors="replace").strip().lower()
        if payload not in SOURCES:
            log.warning("ignoring unknown source: %r", payload)
            return
        if payload == current["source"]:
            log.info("already on %s, republishing state", payload)
            c.publish(TOPIC_STATE, payload, qos=1, retain=True)
            return
        url = SOURCES[payload]
        log.info("switching to %s -> %s", payload, url)
        try:
            mpv.loadfile(url)
        except Exception:
            log.exception("failed to send loadfile to mpv")
            return
        current["source"] = payload
        c.publish(TOPIC_STATE, payload, qos=1, retain=True)

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
        while not shutdown.is_set():
            if mpv.proc and mpv.proc.poll() is not None:
                log.error("mpv exited rc=%s; restarting", mpv.proc.returncode)
                mpv.start(SOURCES[current["source"]])
            time.sleep(1)
    finally:
        try:
            client.publish(TOPIC_AVAIL, "offline", qos=1, retain=True)
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
        mpv.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
