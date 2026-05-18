# zikzak architecture

Decisions specific to the zikzak streaming server, captured during the May
2026 rebuild after the original drive failed. Most of these are non-obvious
and worth re-reading before doing GPU work, kernel updates, or X-related
surgery on this host.

## GPU split

zikzak has two NVIDIA cards. They are pinned to different jobs so encode and
display never compete:

| Card | nvidia-smi index | DRM | Job |
|------|------------------|-----|-----|
| GTX 1080 | 0 | `/dev/dri/card1`, `renderD128` | liquidsoap 4× NVENC encode + optional admin desktop |
| GTX 1060 6GB | 1 | `/dev/dri/card2`, `renderD129` | quadmux kiosk: NVDEC decode + direct DRM display |

Pinning enforcers:
- `CUDA_VISIBLE_DEVICES=1` in `quadmux-display.service` → mpv only sees the
  1060 for both NVDEC and the EGL/GL context.
- `/etc/X11/xorg.conf.d/10-nvidia-single-gpu.conf` with `BusID PCI:1:0:0` +
  `ProbeAllGpus=false` + `AutoAddGPU=false` → Xorg only opens the 1080.
- liquidsoap's NVENC defaults to GPU 0; no explicit pin needed.

If you swap a GPU or move cards in the PCI slots, update both the xorg.conf
BusID and the ansible role defaults (`qm_xorg_primary_busid`, `qm_drm_*`).

## Quadmux kiosk: direct DRM, no X

The kiosk pipeline (mpv → splitter → 4× CRTs) uses **direct DRM/KMS** on the
1060, bypassing X entirely. We do not run a window manager on the kiosk GPU.

```
mpv --vo=gpu --gpu-context=drm \
    --drm-device=/dev/dri/card2 \
    --drm-connector=HDMI-A-2 \
    --drm-mode=1920x1080
```

**Why direct DRM and not X11.** NVIDIA's proprietary driver, when both GPUs
are present, defaults to a PRIME-sink configuration where Xorg grabs DRM
master on both cards. That blocks mpv from grabbing DRM master on the 1060
(it gets `EACCES` / "Permission denied"). Restricting Xorg to the 1080 (see
above) frees the 1060 for direct mpv ownership.

**Why `nvidia_drm.modeset=1` is required.** Without it, even after Xorg
releases the device, atomic modeset commits fail with `EBUSY` because the
driver isn't in kernel-mode-setting mode. The option is set in
`/etc/modprobe.d/nvidia-drm-modeset.conf` and baked into initramfs.
Verify with `cat /sys/module/nvidia_drm/parameters/modeset` (should be `Y`).
The ansible `bootstrap` role's `nvidia.yml` writes the file and runs
`update-initramfs -u` automatically; reboot required after first install.

## Output resolution

Locked at **1920x1080 @ 60Hz** even though the quad splitter advertises 4K
(`3840x2160`) in its EDID. Reasons:
- The downstream CRTs are 4:3 SD analog. The splitter scales each quadrant
  independently. Sending 1080p in keeps mpv compositing cheap and matches
  the natural 4 × 960×540 grid math from `lavfi-complex`.
- 4K input would force the GPU to render 8.3M pixels per frame at 25fps just
  to feed a splitter that downscales each quadrant anyway. No quality win.

If you ever replace the CRTs with HD monitors, revisit `qm_drm_mode` in the
ansible quadmux-display role defaults.

The HDMI splitter feeding the CRTs has a physical **mode button** that is
easy to bump while rearranging cables. If the CRTs start showing 2 channels
per screen instead of 1, the splitter's mode got cycled — see
[troubleshooting.md → Quadmux CRTs Show Wrong Layout](troubleshooting.md#quadmux-crts-show-wrong-layout-multiple-channels-per-screen).
The kiosk script supports a `QM_LAYOUT` env var as a software fallback if
the physical button ever fails.

## mhbn database location

Canonical postgres lives on **loki**, not zikzak. Commit `f483244 Move mhbn
Postgres primary to loki` (March 2026) was the cutover. The empty mhbn DB
that briefly existed on zikzak (created by the bootstrap role on the first
rebuild attempt) was dropped.

zikzak reaches it via an autossh forward tunnel:
```
zikzak:127.0.0.1:5435 → loki:127.0.0.1:5432
```
- Service: `loki-pg-tunnel.service` on zikzak (runs as nthmost).
- DSN for services on zikzak: `postgresql://mhbn:***@127.0.0.1:5435/mhbn`.
- The old `zikzak-pg-tunnel.service` on loki (which tunneled the opposite
  direction back when the DB was on zikzak) is disabled and obsolete.

The loki-pg-tunnel depends on zikzak's nthmost having an SSH key authorized
on both zephyr (for the jump) and loki. See `~/.ssh/config` on zikzak.

## Lightdm autologin + kiosk hygiene

Lightdm is configured to autologin **max** (the service user) on every boot
via `/etc/lightdm/lightdm.conf.d/60-autologin.conf`. Required because:
- `ch1-audio.service` runs as max and needs an active session for ALSA
  device access via the `audio` group.
- The kiosk model assumes max owns the console state at all times so admin
  work happens via SSH, not via the local terminal.

Mint's default autostart entries (`mintupdate`, `warpinator-autostart`,
`user-dirs-update-gtk`) are suppressed in max's `~/.config/autostart/` with
`Hidden=true` overrides. Without this, the update-manager would pop up over
the quadmux output. The list is in the quadmux-display role defaults
(`qm_disable_autostarts`); add to it if Mint ships new noisy autostarts.

## /mnt/media permissions

`/mnt/media` is owned `max:max` with mode `2775` (rwxrwsr-x + setgid). The
admin user (nthmost) is added to the `max` group during bootstrap. This
combo means:
- The dropbox-watchdog (running as max) writes files normally.
- Any ad-hoc rsync as nthmost (the SSH user) creates files that inherit the
  `max` group via setgid, so the watchdog and liquidsoap can read them
  without further chown'ing.
- Avoids the "files arrived but liquidsoap can't open them" failure mode
  that bit the original install.

Codified in the `bootstrap` role's `user.yml` task file.

## Secure Boot and nvidia driver upgrades

zikzak runs Linux Mint with Secure Boot enabled in BIOS. DKMS-built nvidia
modules are signed with a local key (`/var/lib/shim-signed/mok/MOK.der`)
that must be enrolled in shim. The first install requires `mokutil --import`
and console-side enrollment at the MOK Manager screen on reboot — *you
cannot do this remotely*. If you push a kernel upgrade and the new initramfs
rebuilds DKMS with the same key, modules continue to load. If the key ever
rotates, repeat the enrollment.

Symptom of an unenrolled MOK: `nvidia-smi` reports "couldn't communicate
with the NVIDIA driver" and `dmesg` shows `Key was rejected by service`.

## WireGuard endpoint pinning

Both wg0.conf files (zikzak and loki) use an **IP literal** for zephyr's
endpoint (`149.28.77.210:51820`), not the hostname. Reason: `wg-quick@wg0`
starts during early boot before DNS is ready and will silently fail to bring
the tunnel up if the endpoint is a hostname. Both hosts learned this the
hard way in May 2026.

The ansible `wireguard` role enforces this pattern (`wg_hub_endpoint_ip`
var, no DNS lookup at template time).

## Quadmux compositor: scaling limits and design decisions

The quadmux display composites 4 live MPEG-TS streams (from liquidsoap via
local Icecast) into a single 1920x1080 frame for the quad splitter. As of
May 2026, this uses a **hybrid decode** approach:

```
                    ┌──────────────────────────────────────────────┐
                    │              mpv (single process)            │
                    │                                              │
  ch1.ts ─────────► │  ┌─────────┐    ┌───────────┐    ┌────────┐ │
  ch2.ts ─────────► │  │ NVDEC   │───►│ lavfi CPU │───►│ vo=gpu │ │──► HDMI
  ch3.ts ─────────► │  │ decode  │    │ composite │    │ DRM    │ │
  ch4.ts ─────────► │  │ (GPU 1) │    │           │    │        │ │
                    │  └─────────┘    └───────────┘    └────────┘ │
                    └──────────────────────────────────────────────┘
```

**Current resource usage (May 2026 steady state):**
- mpv process: ~80% of one CPU core (~10% of system total)
- System load: ~1.4 on 8 threads (i7-3770K)
- GTX 1060 decoder: ~5% utilization
- GTX 1060 GPU: ~9% utilization
- Memory: ~800 MB

**Why hybrid (NVDEC + CPU composite) instead of pure GPU?**

Pure GPU compositing with ffmpeg CUDA filters (`scale_cuda`, `overlay_cuda`)
was attempted but fails on live streams. The problem: ffmpeg's CUDA hwaccel
requires a clean decode context starting from an IDR frame with valid
SPS/PPS NAL units. When joining a live MPEG-TS mid-GOP (which is always the
case on startup or reconnect), ffmpeg gets continuous "non-existing PPS"
errors and never recovers — it simply never produces output frames.

mpv with `--hwdec=nvdec-copy` handles this gracefully: it uses NVDEC for
decode but copies frames back to CPU memory, allowing lavfi filters to work.
The "copy" path adds ~1ms latency per frame but enables robust stream joining.

**Scaling estimate:**

With load ~1.4 and headroom to ~6.0 before affecting playback quality, zikzak
can theoretically run **3-4 independent quadmux displays** before CPU becomes
the bottleneck. Each additional quadmux would add:
- ~0.8-1.0 load average
- ~800 MB memory
- ~5% decoder utilization on the kiosk GPU

**Practical limits:**
- **GPU outputs:** GTX 1060 has 1x HDMI + 1x DVI-D + 1x DisplayPort. Max 3
  physical outputs, but only one can be DRM master for a single mpv process.
  Multiple quadmuxes would need separate mpv processes with `--drm-connector`
  targeting different outputs.
- **HDMI splitter dependency:** Current setup assumes one composite frame
  split 4 ways. Additional quadmuxes would need their own splitters or a
  different output strategy.
- **Decoder bandwidth:** 4 streams × 1.4 Mbps = 5.6 Mbps decode. The 1060
  can handle 8+ simultaneous 1080p decodes, so this is not a concern.

**Alternative approaches NOT pursued (and why):**

1. **Fix source streams (liquidsoap SPS/PPS injection):** Would require
   modifying liquidsoap's ffmpeg output to inject SPS/PPS before every IDR
   frame (`-x264opts keyint=60:min-keyint=60 -flags +global_header`). Adds
   complexity and may not solve reconnect cases. Not worth it given the
   hybrid approach works well.

2. **GStreamer nvcodec:** GStreamer's `nvh264dec` may handle stream sync
   better, but would require rewriting the entire compositor pipeline.
   Significant effort for uncertain gain.

3. **Hardware video mixer:** A Blackmagic ATEM Mini or similar could do
   4-input compositing in hardware. Cost (~$300) and additional point of
   failure not justified for current use case.

**Conclusion:** The hybrid NVDEC+CPU approach is the right tradeoff. It's
stable, handles stream errors gracefully, and leaves ample headroom for
zikzak's primary job (liquidsoap encoding). If multiple quadmuxes become
a real requirement, the path forward is multiple mpv processes on separate
GPU outputs, not pure-GPU compositing.
