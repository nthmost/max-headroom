"""
Merge philosophy_audio into philosophy.

Moves all files from /mnt/media/philosophy_audio/{short,medium,long}/
into /mnt/media/philosophy/{short,medium,long}/, then updates the DB.

Run on zikzak:
    DATABASE_URL='postgresql://mhbn:PASSWORD@localhost:5432/mhbn' python3 migrate_philosophy.py
"""
import os, shutil, psycopg2, psycopg2.extras

pg = psycopg2.connect(os.environ["DATABASE_URL"])
cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
MEDIA = "/mnt/media"
SRC = os.path.join(MEDIA, "philosophy_audio")
DST = os.path.join(MEDIA, "philosophy")

# ── 1. Move files on disk ──────────────────────────────────────────────────────

moved = 0
for subdir in ("short", "medium", "long"):
    src_dir = os.path.join(SRC, subdir)
    dst_dir = os.path.join(DST, subdir)
    if not os.path.isdir(src_dir):
        continue
    os.makedirs(dst_dir, exist_ok=True)
    for fname in os.listdir(src_dir):
        src_path = os.path.join(src_dir, fname)
        dst_path = os.path.join(dst_dir, fname)
        if os.path.isfile(src_path):
            shutil.move(src_path, dst_path)
            print(f"  moved [{subdir}] {fname}")
            moved += 1

print(f"Moved {moved} file(s) on disk.")

# Remove now-empty philosophy_audio dirs
for subdir in ("short", "medium", "long"):
    d = os.path.join(SRC, subdir)
    if os.path.isdir(d) and not os.listdir(d):
        os.rmdir(d)
if os.path.isdir(SRC) and not os.listdir(SRC):
    os.rmdir(SRC)
    print("Removed empty philosophy_audio directory.")

# ── 2. Update DB ───────────────────────────────────────────────────────────────

cur.execute(
    "UPDATE media_files SET category = 'philosophy' WHERE category = 'philosophy_audio'"
)
print(f"media_files updated: {cur.rowcount} rows")

cur.execute(
    "UPDATE media_file_categories SET category_name = 'philosophy' WHERE category_name = 'philosophy_audio'"
)
print(f"media_file_categories updated: {cur.rowcount} rows")

cur.execute(
    "UPDATE categories SET is_tag_only = TRUE WHERE name = 'philosophy_audio'"
)
print(f"categories: marked philosophy_audio as tag_only")

pg.commit()

# ── 3. Verify ──────────────────────────────────────────────────────────────────

cur.execute("SELECT subdir, COUNT(*) AS n FROM media_files WHERE category = 'philosophy' GROUP BY subdir ORDER BY subdir")
print("\nphilosophy files in DB:")
for row in cur.fetchall():
    print(f"  {row['subdir']}: {row['n']}")

cur.execute("SELECT COUNT(*) AS n FROM media_files WHERE category = 'philosophy_audio'")
remaining = cur.fetchone()["n"]
print(f"philosophy_audio rows remaining: {remaining} (should be 0)")

cur.close()
pg.close()
