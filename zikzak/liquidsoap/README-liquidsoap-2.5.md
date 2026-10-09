# zikzak liquidsoap 2.5.x deployment (hand-built)

**Status (2026-10-07):** zikzak runs **Liquidsoap 2.5.0+git@b5632462c**, hand-built
from source via opam, serving the 4-channel quadmux feed. This replaced the stock
apt **2.2.4** package, which could only decode ~1 channel of video in real time on
the i7-3770K and periodically crawled/livelocked.

## Why 2.5.x (and why from source)

2.5.x makes ffmpeg **decode multithreaded** (`#5014`) and runs clocks as scheduler
tasks across cores. On this 2012 CPU that's the difference between keeping real time
and not: measured **~3.6 cores / ~190 threads, zero sustained catch-up** on 2.5.0,
versus 2.4.5 stuck at ~1.5 cores (heavy channels spiralled) and 2.2.4 single-threaded
(~1 core, drifted into the catch-up/"Too much latency! Resetting active sources"
cycle every few hours).

There is **no prebuilt 2.5.x for Ubuntu noble / Mint 22.3** (ffmpeg 6). Savonet's
rolling debs target newer distros (ffmpeg 7) and their apt repo has no noble rolling
build. So we build from source against the system ffmpeg 6.

## What's deployed

- **Binary:** `/opt/liquidsoap-2.5/bin/liquidsoap` (+ stdlib at
  `/opt/liquidsoap-2.5/share/liquidsoap-lang/libs/`), copied from the opam build in
  `/home/nthmost/.opam/liq25/`. Dynamically links the system ffmpeg-6 `.so`s.
- **Config:** `/home/max/liquidsoap/channels.liq` — 2.5.x-migrated (see repo
  `ansible/roles/liquidsoap/templates/channels.liq.j2` and the reference
  `zikzak/liquidsoap/channels.liq`).
- **Encoder wrapper:** `/home/max/liquidsoap/encode-ch.sh` — the external NVENC
  ffmpeg invocation (2.5.x `output.external` execs argv with no shell, so quoting
  lives in this script). Uses the **system** ffmpeg (has `h264_nvenc`).
- **Service override:** `/etc/systemd/system/zikzak-liquidsoap.service.d/liq25.conf`
  points `ExecStart` at the /opt binary with `--stdlib`:
  ```ini
  [Service]
  ExecStart=
  ExecStart=/opt/liquidsoap-2.5/bin/liquidsoap --stdlib /opt/liquidsoap-2.5/share/liquidsoap-lang/libs/stdlib.liq /home/max/liquidsoap/channels.liq
  ```
- The base `zikzak-liquidsoap.service` (User=max, MemoryHigh=2G/MemoryMax=3G) and the
  `liquidsoap-watchdog` / `daily-display-restart` safety nets are unchanged.

## Rebuild from scratch (opam)

```bash
# as nthmost (has sudo, so opam depext can apt-install system -dev libs)
sudo apt-get install -y opam m4
opam init --bare -y --disable-sandboxing
opam switch create liq25 ocaml-base-compiler.5.5.0 -y     # compiles OCaml 5.5 (~slow on this CPU)
eval "$(opam env --switch=liq25)"
export OPAMCONFIRMLEVEL=unsafe-yes OPAMYES=1
git clone --recursive -b rolling-release-v2.5.x https://github.com/savonet/liquidsoap.git ~/liquidsoap-src
cd ~/liquidsoap-src
opam pin add -y -n .
opam install -y ffmpeg        # ocaml ffmpeg bindings (+ depext pulls libav*-dev)
opam install -y liquidsoap

# deploy to /opt (so the `max` service user can run it, independent of nthmost's home)
sudo mkdir -p /opt/liquidsoap-2.5/bin /opt/liquidsoap-2.5/share
sudo cp ~/.opam/liq25/bin/liquidsoap /opt/liquidsoap-2.5/bin/
sudo cp -r ~/.opam/liq25/share/liquidsoap-lang /opt/liquidsoap-2.5/share/
sudo chmod -R a+rX /opt/liquidsoap-2.5
```

Validate the config before restarting (note `--stdlib` points at the **file**):
```bash
sudo -u max /opt/liquidsoap-2.5/bin/liquidsoap \
  --stdlib /opt/liquidsoap-2.5/share/liquidsoap-lang/libs/stdlib.liq \
  --check /home/max/liquidsoap/channels.liq
```

## Gotchas learned

- The opam build installs `/opt`-copied stdlib with the **compiled-in** path pointing
  at the opam prefix; running the /opt copy standalone needs `--stdlib <stdlib.liq>`.
- `--stdlib` takes the `stdlib.liq` **file**, not the libs directory.
- Config migration from 2.2.4 → 2.5.x: `log.file.*` → `settings.log.file.*`;
  `on_track(f)` → `on_track(synchronous=false, f)`; `random(weights=[..],[..])` →
  per-source `src.{weight=N}`; `output.external.ffmpeg(cmd,src)` →
  `output.external(%ffmpeg(format="avi", %video(codec="rawvideo"),
  %audio(codec="pcm_s16le")), cmd, src)`; `settings.frame.video.width/height` still
  valid (must stay 960x720 for NVENC stride).
- Do **not** force a shared clock (`clock.assign_new`) — in 2.5.x that serializes
  decode onto one thread and reintroduces the spiral. Per-output clocks parallelize.
- Video content type is now `yuv420p` (was `canvas`) — harmless unless you have
  explicit `source(video=canvas)` annotations.

## Rollback to 2.2.4

```bash
sudo systemctl stop liquidsoap-watchdog.timer
sudo rm /etc/systemd/system/zikzak-liquidsoap.service.d/liq25.conf
sudo cp ~/liquidsoap-rollback/channels.liq.pre-upgrade /home/max/liquidsoap/channels.liq
sudo apt-get install -y --allow-downgrades ~/liquidsoap-rollback/liquidsoap_2.2.4-1_amd64.deb
sudo systemctl daemon-reload && sudo systemctl restart zikzak-liquidsoap quadmux-display
sudo systemctl start liquidsoap-watchdog.timer
```
(`~/liquidsoap-rollback/` on zikzak holds both debs + the pre-upgrade config.)

## Ansible caveat

The `liquidsoap` role's config + `encode-ch.sh` templates are 2.5.x-correct, but the
role still **installs the 2.2.4 apt package and a service unit with the old ExecStart**.
It does NOT build/deploy the 2.5.x binary or the drop-in. **Do not run this role against
zikzak** until it's extended to (a) ensure the /opt 2.5.x binary and (b) set ExecStart
to it — otherwise it reverts the interpreter to an incompatible 2.2.4.
