# Bug report: `output.external.ffmpeg` pipes do not recover after a sustained clock-latency spiral (persistent livelock; full restart required)

**Target project:** [savonet/liquidsoap](https://github.com/savonet/liquidsoap)

## Summary

We run a 4-channel video streamer in Liquidsoap (four `output.external.ffmpeg`
outputs, each piping raw video+audio to an `ffmpeg` child that NVENC-encodes to
H.264 and publishes to a local Icecast). Under sustained CPU pressure the main
clock falls behind real time and logs `We must catchup N seconds!` indefinitely,
eventually hitting `Too much latency! Resetting active sources...`.

The reportable problem is the **end state**: once the latency spiral is deep
enough, the four `output.external.ffmpeg` child processes receive
`Sys_error("Broken pipe")`, and **Liquidsoap never recovers them**. The ffmpeg
children stay alive (and the `reopen_on_error` logic keeps firing) but Liquidsoap
stops feeding any of them, so **no mountpoint is ever published again**. From the
consumer side every Icecast mount returns `404` until the Liquidsoap *process* is
restarted. "Resetting active sources" does not restore output; only a full
process restart does.

There is also a **secondary observation of unbounded RSS growth** that we suspect
is related (it makes the box more likely to tip into the spiral, and our cgroup
`MemoryHigh` containment may in turn feed the spiral — see caveats).

We want to (a) report the non-recovery behavior, and (b) ask whether the RSS
growth is a known leak or expected for this topology.

## Environment

| | |
|---|---|
| Liquidsoap | **2.2.4-1+dev** (Debian/Ubuntu package `liquidsoap 2.2.4-1`, `/usr/bin/liquidsoap`) |
| OS | Linux Mint 22.3 (Ubuntu 24.04 base) |
| Kernel | 6.17.0-23-generic |
| CPU | Intel Core i7-3770K @ 3.5 GHz (4c/8t, 2012-era Ivy Bridge) |
| RAM / swap | 16 GiB / 2 GiB |
| GPUs | NVIDIA GTX 1080 (8 GB) + GTX 1060 (6 GB) — used for NVENC on the **output** side only |
| Managed by | systemd `Type=simple`, `Restart=always`, running as a non-root user |
| cgroup limits | `MemoryHigh=2G`, `MemoryMax=3G` (our mitigation — see caveats) |

We are aware 2.2.4 is not current; we can retest on a newer release if that would
help triage (see "What we can do next").

## Topology

- **Input:** four independent channels, each a `random`/`rotate` composition of
  `playlist(mode="randomize", reload_mode="watch", ...)` sources reading local
  `.mp4` files (mixed H.264/AAC, various resolutions, normalized to a
  960×720 canvas, 25 fps). Decoding is Liquidsoap's internal ffmpeg decoder, i.e.
  **software H.264 decode on the CPU**.
- **Output:** four `output.external.ffmpeg(...)`, each spawning:

  ```
  ffmpeg -f avi -vcodec rawvideo -r 25 -acodec pcm_s16le -i pipe:0 \
    -r 25 -vf "format=yuv420p" \
    -c:v h264_nvenc -preset p4 -profile:v high \
    -b:v 1400k -maxrate 1400k -bufsize 2800k -g 60 \
    -c:a aac -b:a 128k -ac 2 -ar 44100 \
    -af "aresample=async=1" -max_muxing_queue_size 1024 \
    -f mpegts icecast://source:***@localhost:8000/chN.ts
  ```

  So Liquidsoap muxes **raw video (AVI/rawvideo) + PCM audio** into each child's
  stdin. At 960×720 YUV420 that is ~1.04 MB/frame × 25 fps ≈ **26 MB/s per
  channel ≈ ~104 MB/s of raw frames across the four pipes**, on top of decoding
  four H.264 inputs in software. Only the final encode is GPU-accelerated.

Relevant output declaration:

```liquidsoap
output.external.ffmpeg(id="enc_ch1", show_command=true,
  reopen_on_error=fun (_)->5., encoder_cmd("/ch1.ts"), ch1)
# ...ch2, ch3, ch4 identical
```

(Full config is attached below.)

## Observed behavior

### 1. The clock never keeps up, from day one

Our log (`log.file`) spans ~5 months of continuous operation. Signature counts
in a single 289 MB log file:

| Signature | Count |
|---|---|
| `We must catchup N seconds!` | **2,761,466** |
| `Too much latency! Resetting active sources...` | 1,842 |
| `Error while streaming: ... Sys_error("Broken pipe")` | 13,554 |

The very first `We must catchup` appears on the config's **first day of
operation** (`We must catchup 7.41 seconds!`), i.e. the box has never been able
to sustain this workload in real time. Normally this is tolerable — small
catchups recover — but periodically it spirals.

### 2. The spiral and the broken-pipe cascade

A representative spiral (the one that prompted this report):

```
2026/10/05 19:10:38 [clock.main:2] Too much latency! Resetting active sources...
2026/10/05 19:10:53 [clock.main:2] We must catchup 14.70 seconds!
2026/10/05 19:11:00 [clock.main:2] We must catchup 21.66 seconds!
2026/10/05 19:11:16 [clock.main:2] We must catchup 37.04 seconds!
2026/10/05 19:11:29 [clock.main:2] We must catchup 50.37 seconds!
2026/10/05 19:11:34 [clock.main:2] We must catchup 54.74 seconds!
2026/10/05 19:11:37 [enc_ch1:3] Error while streaming: Lang.Runtime_error {
  kind: "system", msg: "Sys_error(\"Broken pipe\")",
  pos: [at stdlib.ml, line 379, char 33-33,
        at src/core/outputs/pipe_output.ml, line 417, char 36-36] },
  will re-open in 5.00s
2026/10/05 19:11:38 [enc_ch4:3] Error while streaming: ... Sys_error("Broken pipe") ... will re-open in 5.00s
2026/10/05 19:11:38 [enc_ch2:3] Error while streaming: ... Sys_error("Broken pipe") ... will re-open in 5.00s
2026/10/05 19:11:38 [enc_ch3:3] Error while streaming: ... Sys_error("Broken pipe") ... will re-open in 5.00s
2026/10/05 19:11:38 [clock.main:2] We must catchup 59.35 seconds!
```

Once the catchup reaches this depth, **all four outputs break within ~1 second**
and the `We must catchup` line stabilizes around 58–59 s — i.e. the clock is
pegged ~1 minute behind and stops closing the gap.

### 3. The non-recovery (the actual bug)

After the cascade:

- The four `ffmpeg` child processes **remain alive** (visible in `ps`, parented
  to the Liquidsoap process).
- `reopen_on_error=fun (_)->5.` keeps scheduling reopens, but **no mountpoint is
  ever (re)published**. Icecast's access log shows **only consumer `GET`s
  returning 404 — zero new source connections** from the ffmpeg children after
  the cascade.
- Consequently every downstream consumer (our compositor + relays) gets `404`
  on all four mounts **indefinitely**.
- `systemctl status` shows the service `active (running)` the entire time — there
  is no crash, no exit, no self-heal.
- **Only a full process restart** (`systemctl restart`) recovers: on restart the
  mounts repopulate within ~5 seconds and stay healthy for hours/days until the
  next spiral.

In other words: the documented recovery mechanism ("Too much latency! Resetting
active sources...") runs, but the `output.external.ffmpeg` outputs are left in a
permanently wedged state that the reset does not clear.

### 4. Secondary: RSS growth over uptime

- Fresh after restart: **~415 MB RSS** (~11 min uptime).
- Grows steadily to **2 GB+** over hours/days; we have previously observed
  **~7.5 GB RSS after ~3 days** on this box before we added cgroup limits.

We cannot yet say whether this is a genuine leak or expected buffering/retention
for a 4× software-decode video topology. It is plausibly linked to the spiral:
higher RSS → swap pressure / allocator work → the clock falls further behind.

## What we think is happening (hypotheses, clearly labeled)

We are not claiming certainty on root cause; these are our best guesses and we
defer to the maintainers:

1. **Throughput deficit is the trigger, not the bug.** A 2012 CPU doing 4×
   software H.264 decode + ~104 MB/s of raw-frame pipe writes is at the edge of
   real time; a transient hiccup pushes it behind. That part is arguably "buy a
   faster CPU / use fewer channels." **The bug is that Liquidsoap doesn't recover
   the external outputs once it falls far enough behind** — it should either
   drop/catch up frames and resume feeding the pipes, or tear down and respawn
   the `output.external.ffmpeg` children so publishing resumes without a full
   process restart.

2. **Possible contributor: blocking work in `on_track`.** Each channel's
   `on_track` handler calls `process.run` several times (spawns `sh` + `python3`
   + `curl` to push now-playing metadata to two Icecast servers), synchronously,
   on every content track change. If these run on a streaming/clock thread, a
   slow `process.run` (DNS to the remote Icecast, python startup) could inject
   latency that helps tip the clock into the spiral. We can move this off the hot
   path to test — guidance welcome on whether `on_track` callbacks block the
   source clock in 2.2.x.

3. **Possible leak in the decode/output retention path**, independent of the
   above, given the sustained RSS climb from ~400 MB to multi-GB.

## Caveats / things that are *our* doing (disclosed in good faith)

- The `MemoryHigh=2G` / `MemoryMax=3G` cgroup limits are **our** mitigation, not
  stock. `memory.high` throttles via reclaim once hit, which adds CPU stalls —
  so after RSS reaches 2 GB our own containment may *worsen* the latency and help
  trigger the spiral. A clean repro should probably remove these limits (we kept
  them because without `MemoryMax` the box previously OOM-thrashed into a hard
  freeze).
- We run an old packaged 2.2.4; we have not yet reproduced on current `main`.
- The per-track `process.run` metadata pushes are non-idiomatic and we're happy
  to remove them for a minimal repro.
- Occasional per-file decoder errors also appear in the log
  (`Faad.Failed`, `Avutil.Error(Invalid data found when processing input)`,
  `Available decoders cannot decode ...`) but these are transient, recover on
  their own, and do **not** line up in time with the spirals — we don't think
  they're related, but mention them for completeness.

## What we can do next (to help triage)

- Retest on a current Liquidsoap release (2.3.x/2.4.x) and report whether the
  non-recovery persists.
- Produce a minimal repro: drop to 1 channel, remove the `on_track`
  `process.run` calls, remove the cgroup limits, and artificially starve the
  clock (e.g. `cpulimit`/`nice` or a smaller canvas on a slow VM) to force the
  spiral, then confirm whether the external output self-recovers.
- Capture `telnet` (`output.external.ffmpeg` status), `/proc/<pid>/status`,
  and allocator stats during a spiral if that would be useful.

Tell us which of these is most useful and we'll gather it.

## Appendix: full `channels.liq`

```liquidsoap
# (channel compositions elided for brevity in this excerpt; the load-bearing
#  parts are the canvas settings and the four external outputs)

settings.frame.video.width.set(960)
settings.frame.video.height.set(720)

let nvenc_cmd_base =
  "-r 25 " ^
  "-vf \"format=yuv420p\" " ^
  "-c:v h264_nvenc -preset p4 -profile:v high " ^
  "-b:v 1400k -maxrate 1400k -bufsize 2800k -g 60 " ^
  "-c:a aac -b:a 128k -ac 2 -ar 44100 " ^
  "-af \"aresample=async=1\" " ^
  "-max_muxing_queue_size 1024 " ^
  "-f mpegts "

def encoder_cmd(mount) =
  nvenc_cmd_base ^ "icecast://source:***@localhost:8000" ^ mount
end

# each channel = random()/rotate() over playlist(reload_mode="watch") sources,
# wrapped in mksafe(); on_track pushes now-playing metadata via process.run.

output.external.ffmpeg(id="enc_ch1", show_command=true, reopen_on_error=fun (_)->5., encoder_cmd("/ch1.ts"), ch1)
output.external.ffmpeg(id="enc_ch2", show_command=true, reopen_on_error=fun (_)->5., encoder_cmd("/ch2.ts"), ch2)
output.external.ffmpeg(id="enc_ch3", show_command=true, reopen_on_error=fun (_)->5., encoder_cmd("/ch3.ts"), ch3)
output.external.ffmpeg(id="enc_ch4", show_command=true, reopen_on_error=fun (_)->5., encoder_cmd("/ch4.ts"), ch4)
```

---

*This issue was researched and drafted by **Claude Code** (Anthropic's agentic
coding tool) — it collected the environment facts, log signatures, and config
directly from the affected host and wrote this report. It was **overseen,
reviewed, and verified by its pilot human** before submission. We're happy to
run any follow-up diagnostics the maintainers request.*
