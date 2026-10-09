# zikzak liquidsoap 2.5.x deployment (hand-built)

**Status (2026-10-08):** zikzak runs **Liquidsoap 2.5.0+git@b5632462c**, hand-built
from source via opam and **linked against an isolated ffmpeg 7** in `/opt/ffmpeg7`,
serving the 4-channel quadmux feed. This replaced the stock apt **2.2.4** package,
which could only decode ~1 channel of video in real time on the i7-3770K and
periodically crawled/livelocked.

## Why 2.5.x (and why ffmpeg 7)

2.5.x makes ffmpeg **decode multithreaded** (`#5014`) and runs clocks as scheduler
tasks across cores. On this 2012 CPU that's the difference between keeping real time
and not: measured **~3.6 cores / ~190 threads, zero sustained catch-up** on 2.5.0,
versus 2.4.5 stuck at ~1.5 cores (heavy channels spiralled) and 2.2.4 single-threaded
(~1 core, drifted into the catch-up/"Too much latency! Resetting active sources"
cycle every few hours).

**ffmpeg 7 is mandatory.** 2.5.x's decode/scale filtergraph passes a `range` option to
ffmpeg's `buffer` filter that only exists in **ffmpeg 7+**. Built against noble's
**ffmpeg 6**, any input file carrying color-range metadata fails to decode
(`[buffer] No such option: range.` → `Avutil.Error(Option not found)`). ch2/3/4's
content mostly isn't range-tagged so they survived, but ch1 (music + interstitials,
all YouTube-sourced → range-tagged) failed WHOLESALE: it churned through unplayable
files, burned CPU, and stalled within ~4-12 min. This is NOT config-fixable (proved
independent of channel structure; no setting disables the option).

There is **no prebuilt 2.5.x for noble** (ffmpeg 6), and noble has no ffmpeg 7. So we
build ffmpeg 7 into its own prefix (`/opt/ffmpeg7`) and link liquidsoap against it,
running the service with `LD_LIBRARY_PATH=/opt/ffmpeg7/lib`. The **system ffmpeg stays
6**, untouched — mpv (quadmux display), `encode-ch.sh` (NVENC), and the mhbn relays all
keep using it. Only the liquidsoap process sees ffmpeg 7.

## What's deployed

- **ffmpeg 7:** `/opt/ffmpeg7/` (ffmpeg 7.1.1, shared libs, LGPL build — libs only, no
  CLI). Provides `libav*.so.61/.59`, `libsw*`, `libavfilter.so.10`.
- **Binary:** `/opt/liquidsoap-2.5/bin/liquidsoap` (+ stdlib at
  `/opt/liquidsoap-2.5/share/liquidsoap-lang/libs/`), copied from the opam build in
  `/home/nthmost/.opam/liq25/`. Links the **ffmpeg 7** `.so.61` set from `/opt/ffmpeg7`
  (needs `LD_LIBRARY_PATH=/opt/ffmpeg7/lib` at runtime — set in the drop-in).
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
  Environment=LD_LIBRARY_PATH=/opt/ffmpeg7/lib
  Environment=LIQ_CACHE_SYSTEM_DIR=/home/max/.cache/liquidsoap
  Environment=LIQ_CACHE_USER_DIR=/home/max/.cache/liquidsoap
  ExecStart=
  ExecStart=/opt/liquidsoap-2.5/bin/liquidsoap --stdlib /opt/liquidsoap-2.5/share/liquidsoap-lang/libs/stdlib.liq /home/max/liquidsoap/channels.liq
  ```
  (`LIQ_CACHE_*` point liquidsoap's stdlib cache at a max-writable dir; the compiled-in
  default is nthmost's opam prefix, which the `max` service user can't write.)
- The base `zikzak-liquidsoap.service` (User=max, MemoryHigh=2G/MemoryMax=3G) and the
  `liquidsoap-watchdog` / `daily-display-restart` safety nets are unchanged.

## Rebuild from scratch (opam)

### 1. Build ffmpeg 7 into /opt/ffmpeg7

```bash
sudo apt-get install -y nasm
cd ~ && curl -fsSL https://ffmpeg.org/releases/ffmpeg-7.1.1.tar.xz | tar xJ && cd ffmpeg-7.1.1
./configure --prefix=/opt/ffmpeg7 --enable-shared --disable-static --disable-programs --disable-doc --disable-ffplay --enable-pic
make -j"$(nproc)" && sudo make install
# sanity: should print 61.x
PKG_CONFIG_PATH=/opt/ffmpeg7/lib/pkgconfig pkg-config --modversion libavcodec
```

### 2. Build liquidsoap 2.5.x against it

```bash
# as nthmost (has sudo, so opam depext can apt-install system -dev libs)
sudo apt-get install -y opam m4
opam init --bare -y --disable-sandboxing
opam switch create liq25 ocaml-base-compiler.5.5.0 -y     # compiles OCaml 5.5 (~slow on this CPU)
eval "$(opam env --switch=liq25)"
export OPAMCONFIRMLEVEL=unsafe-yes OPAMYES=1
export PKG_CONFIG_PATH=/opt/ffmpeg7/lib/pkgconfig       # <-- so the bindings link ffmpeg 7
git clone --recursive -b rolling-release-v2.5.x https://github.com/savonet/liquidsoap.git ~/liquidsoap-src
cd ~/liquidsoap-src
opam pin add -y -n .
# Build the av* bindings (they link libav) + liquidsoap AGAINST ffmpeg 7. NB: the
# package names are ffmpeg-av* (there is NO ffmpeg-avformat; avformat is in ffmpeg-av).
opam install -y ffmpeg-avutil ffmpeg-avcodec ffmpeg-avfilter ffmpeg-swresample \
  ffmpeg-swscale ffmpeg-avdevice ffmpeg-av ffmpeg liquidsoap
# verify the binary links .so.61 (ffmpeg 7), not .60:
ldd ~/.opam/liq25/bin/liquidsoap | grep -oE 'libavcodec.so.[0-9]+'

# deploy to /opt (so the `max` service user can run it, independent of nthmost's home)
sudo mkdir -p /opt/liquidsoap-2.5/bin /opt/liquidsoap-2.5/share
sudo cp ~/.opam/liq25/bin/liquidsoap /opt/liquidsoap-2.5/bin/
sudo cp -r ~/.opam/liq25/share/liquidsoap-lang /opt/liquidsoap-2.5/share/
sudo chmod -R a+rX /opt/liquidsoap-2.5
```

If you ever rebuild only the bindings against a new ffmpeg, reinstall the **ffmpeg-av\***
sub-packages (not just the `ffmpeg` meta) with `PKG_CONFIG_PATH` set — the meta alone
does not re-link libav, so the binary keeps the old soname.

Validate the config before restarting (note `--stdlib` points at the **file**, and
`LD_LIBRARY_PATH` must be set so it finds the ffmpeg 7 `.so`s):
```bash
sudo -u max env LD_LIBRARY_PATH=/opt/ffmpeg7/lib HOME=/home/max \
  /opt/liquidsoap-2.5/bin/liquidsoap \
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
