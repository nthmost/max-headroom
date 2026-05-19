# Catalog reconciliation

When `mhbn.media_files` drifts from the actual files in `/mnt/media/` on
zikzak — usually after disk rebuilds, partial rsyncs, or out-of-band content
changes — use this runbook to pull them back in sync.

The 2026-05-18 session reduced the catalog from 957 rows / 938 files with
137 missing-on-disk and 118 missing-in-DB → 920 / 920 with zero gap, using
the three-phase approach below. The scripts live in `intake/` (see
`integrity_check.py` for the inventory baseline).

## Phase 1 — get the picture

Run from zikzak (or from anywhere with the loki-pg-tunnel reachable):

```bash
DATABASE_URL=postgresql://mhbn:***@127.0.0.1:5435/mhbn \
MEDIA_ROOT=/mnt/media \
python3 intake/integrity_check.py
```

Outputs three sets:
- **Cleanly matched**: row + file at the same path. No work needed.
- **IN DB BUT MISSING ON DISK**: row points at a file that's not there.
- **ON DISK BUT NOT IN DB**: file with no row.

The interesting work is in the second two sets. Often they're not
unrelated lists — they're the **same files at different paths**.

## Phase 2 — pair them up (the "path schism" case)

Most "missing" + "extra" file pairs are the same content under different
paths. Common causes:

1. **Operator reorganization without DB update.** Files moved on disk
   (e.g. `cartoons/short/X.mp4` → `surreal_talkshows/short/X.mp4`) but
   the DB row still points at the canonical location.

2. **rsync of a host that itself had both layouts.** This bit us hard:
   loki's `/mnt/media_transcoded/` contained both sub-category dirs
   (`gaelic_resistance/short/`) AND canonical dirs (`music/short/`) with
   *identical content* in each — likely from an earlier reorganization
   attempt on loki. Our rsync mirrored both, so zikzak ended up with the
   same file at two paths, and only one had a DB row. **md5 the
   duplicates before deleting** — sometimes the sub-cat version is
   newer/different.

3. **Extension drift.** Transcoded `.mp4` on disk but DB still has the
   original `.webm` / `.mkv` from the IA download.

## Phase 3 — execute the migration

The 2026-05-18 session used three scripts that lived in `/tmp/` while
running. The patterns are reusable; preserve any of these as scripts in
this repo when they're needed again.

### Op 1 — pair-by-basename moves

For DB rows whose canonical path is missing on disk, look for a same-
basename file elsewhere on disk and move it to the canonical location.
Add the sub-category dir name as a non-primary tag (so `surreal_talkshows`
becomes a tag on items moved to `cartoons` or `tv_shows`).

Key safety properties of the script that worked:
- **Refuses to overwrite** if the target path already has a file.
- **Idempotent**: rerunning after partial success skips already-moved items.
- **One DB transaction** wrapping all the tag/filename updates so a
  failure mid-run doesn't half-apply.
- **Doesn't tag with the primary category**: when the disk path and DB
  category match (e.g. `music/long/X.webm` row, `music/long/X.mp4` disk),
  it's just an extension correction — no `music` tag added.

### Op 2 — handle truly-orphan DB rows

For DB rows that point at files which don't exist on disk *and* don't
exist on loki (origin) either: mark `is_active = FALSE` so they drop out
of listings without losing the audit trail. Export the orphans
(`id, url, title, source, category, length, tags, ingest_date, job context`)
to a JSON file first — in case the content needs re-acquiring later from
YouTube/IA. The 2026-05-18 export landed at
`~/orphan-media-export-<date>.json` on zikzak.

### Op 3 — catalog unindexed disk files

For files on disk with no DB row:
1. If the file is already at a canonical-style path
   (`interstitials/short/`, `music/long/`, `prelinger/<topic>/`, etc.) —
   just insert a `media_files` row with `ffprobe` metadata.
2. If the file is at a sub-category path AND the canonical equivalent
   already exists — **md5-compare**, then delete the sub-category
   duplicate and ensure the canonical row exists + tagged.
3. If the file is at a sub-category path AND no canonical equivalent
   exists — move it and insert a row + tag.

The duplicate-vs-conflict decision (md5 match vs differ) matters. The
script in this session used `md5sum size + first 4MB` as a fast hash —
sufficient to spot identical files without reading 800MB. If md5s
differ, leave both in place and flag for operator review.

## Verification

After running all phases, re-run `integrity_check.py`. Expect 0/0 gap
on both sides. Also sanity-check primary-category distribution against
the canonical 12 in `intake/config.py:CATEGORIES`:

```sql
SELECT category, COUNT(*) FROM media_files
WHERE is_active = TRUE GROUP BY category ORDER BY 2 DESC;
```

Anything outside the canonical 12 means a sub-category dir leaked into
`media_files.category` — that's a sign Op 1 missed a move, or new
content was added to a non-canonical dir since.

## Liquidsoap impact

None during the migration. Liquidsoap watches the source directories via
`reload_mode="watch"` (inotify), so file moves immediately update its
random-source pools. The streams don't even hiccup.
