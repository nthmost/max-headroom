# Zikzak audio switcher

MQTT-controlled audio source for zikzak's 3.5mm jack. Replaces `ch1-audio.service`.

A long-running `mpv` plays one of:

| Source | URL |
|--------|-----|
| `ch1`  | `http://localhost:8000/ch1.ts` (default) |
| `knob` | `http://10.21.1.44:8000/stream.ogg` (KNOB on beyla) |

Switching is gapless-ish: the controller sends `loadfile` to mpv over its
IPC socket, so the process stays up and ALSA isn't reopened.

## MQTT topics

| Topic | Direction | Payload |
|-------|-----------|---------|
| `zikzak/audio/source/set` | HA -> zikzak | `ch1` or `knob` |
| `zikzak/audio/source`     | zikzak -> HA (retained) | current source |
| `zikzak/audio/available`  | LWT (retained) | `online` / `offline` |
| `homeassistant/select/zikzak_audio/config` | discovery (retained) | auto-creates the HA select entity |

Because the discovery payload is published on connect, no Home Assistant
configuration is required — the `select.zikzak_audio` entity appears
automatically once MQTT discovery is enabled (it is, by default).

## Deploy

On zikzak (as root):

```bash
# 1. drop the controller into place
sudo install -d /opt/max-headroom/zikzak/bin
sudo install -m 0755 zikzak/bin/audio-switcher.py /opt/max-headroom/zikzak/bin/

# 2. install paho-mqtt
sudo apt install -y python3-paho-mqtt

# 3. env file with MQTT creds (mode 0640, root:nthmost)
sudo install -d -m 0750 -o root -g nthmost /etc/zikzak
sudo tee /etc/zikzak/audio-switcher.env >/dev/null <<'EOF'
MQTT_HOST=10.21.0.43
MQTT_PORT=1883
MQTT_USER=wiresprite
MQTT_PASS=wiresprite-eats-42-wires!
AUDIO_DEVICE=alsa/plughw:0,0
DEFAULT_SOURCE=ch1
EOF
sudo chmod 0640 /etc/zikzak/audio-switcher.env
sudo chown root:nthmost /etc/zikzak/audio-switcher.env

# 4. systemd unit
sudo install -m 0644 zikzak/systemd/zikzak-audio.service /etc/systemd/system/
sudo systemctl daemon-reload

# 5. cut over from ch1-audio.service
sudo systemctl disable --now ch1-audio.service
sudo systemctl enable --now zikzak-audio.service
sudo systemctl status zikzak-audio.service
```

## Verify

```bash
# from any host with the wiresprite creds
mosquitto_pub -h 10.21.0.43 -u wiresprite -P 'wiresprite-eats-42-wires!' \
  -t zikzak/audio/source/set -m knob

mosquitto_sub -h 10.21.0.43 -u wiresprite -P 'wiresprite-eats-42-wires!' \
  -t 'zikzak/audio/#' -v
```

The HA select entity `select.zikzak_audio` will show up under MQTT devices
after the service first connects.
