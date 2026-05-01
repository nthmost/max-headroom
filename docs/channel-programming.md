# Channel Programming

Describes the liquidsoap source layout and content weights for each channel.
Implemented in `zikzak/liquidsoap/channels.liq`.

## How It Works

Liquidsoap reads directly from media directories using `playlist(mode="randomize",
reload_mode="watch", <dir>)`. The `watch` mode monitors each directory with inotify,
so new files added to `/mnt/media/` are picked up automatically — no playlist
regeneration step needed.

## CH1 — Long-Form Music

**Intent:** Uninterrupted long-form music sets, concerts, DJ mixes.

**Sources:**
- `music/long/`
- `interstitials/` (one interstitial after every music track)

**Logic:** `rotate([music_long, interstitials])` — strictly alternates one track
then one interstitial. Never two music tracks back-to-back, never two interstitials.

---

## CH2 / CH3 / CH4 — Programmed Channels

**Intent:** Varied general programming with balanced genre representation.
Prelinger archive is weighted to prevent it from crowding out other categories
(it has ~800 files vs ~100 for all other categories combined).

**Sources and weights:**

| Source | Weight | Categories included |
|--------|--------|---------------------|
| `medium_cats` | 1 | cartoons, gaming, philosophy, tv_shows (medium-length) |
| `short_cats` | 3 | anime, cartoons, comedy, documentaries, gaming, philosophy, tv_shows (short) |
| `prelinger` | 5 | prelinger (all era/topic subdirs, combined) |
| `interstitials` | 1 | interstitials/ |
| `commercials` | 1 | commercials/short/ |

**Logic:** `random(weights=[1, 3, 5, 1, 1], [...])` — each track selection
is a weighted random draw. Total weight 11 → roughly 9 content selections per
2 insert selections ≈ one break every 4–5 programs.

`short_cats` and `medium_cats` are themselves `random()` sources that cycle
across their constituent categories, so no single category dominates within
the short or medium pool.

---

## Adding a New Category

Add `dir_src("#{media}/<category>/short")` to `short_cats` and/or
`dir_src("#{media}/<category>/medium")` to `medium_cats` in
`make_programmed_channel()`. The change takes effect after restarting liquidsoap.

Music-only categories with long sets should go in `music/long/` (ch1 pool),
not in the programmed channels.

---

## Category Inventory (as of 2026-05)

| Category | Approx files | Subdirs |
|----------|-------------|---------|
| prelinger | ~800 | era/topic (1940s, 1950s, atomic, industrial, …) |
| gaming | ~35 | short/medium |
| cartoons | ~25 | short/medium |
| comedy | ~20 | short/medium |
| music | ~38 | short/medium/long |
| tv_shows | ~7 | short/medium |
| anime | ~4 | short/medium |
| philosophy | ~2 | short/medium |
| commercials | ~2 | short (only short used by ch2/3/4) |
| documentaries | ~1 | short/medium |
| action | ~1 | short/medium |
| interstitials | ~1 | (flat, no length subdir) |

---

## Reference Playlists

`/home/max/playlists/` on zikzak contains pre-generated M3U files (from
`gen-playlists.sh` / `regenerate-playlists.sh`). These are **not** used by
liquidsoap for programming — they exist for diagnostics, external players,
and auditing what files are present in each category.
