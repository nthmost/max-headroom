# Channel Programming

Defines the intent and content mix for each of the 4 liquidsoap channels.
Used to guide playlist generation weights and category assignments.

## CH1 — Music

**Intent:** Music videos only. Long-form sets, concerts, DJ mixes welcome.
No films, no TV, no archive footage.

**Playlist:** `music-long.m3u`
**Sources:** `music/long/`

---

## CH2 — TBD

**Intent:** TBD

---

## CH3 — TBD

**Intent:** TBD

---

## CH4 — TBD

**Intent:** TBD

---

## Content Weights

The current `short-medium.m3u` playlist (used by ch2/3/4) is an unweighted mix.
With 803 prelinger files vs ~90 files of other content, prelinger dominates ~90% of airtime.

Future work: generate weighted playlists so each category gets proportional representation
regardless of how many files it has. One approach is to interleave N files from each category
rather than dumping everything into a single sorted list.

## Category Inventory (as of 2026-04)

| Category | Files | Length subdirs |
|---|---|---|
| prelinger | 803 | thematic (no length classification) |
| gaming | 35 | short/medium |
| cartoons | 25 | short/medium |
| comedy | 20 | short/medium |
| music | 38 | short/medium/long |
| tv_shows | 7 | short/medium |
| anime | 4 | short/medium |
| philosophy | 2 | short/medium |
| commercials | 2 | short/medium |
| documentaries | 1 | short/medium |
| action | 1 | short/medium |
| interstitials | 1 | (used inline by liquidsoap) |
