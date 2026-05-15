"""
Misc category cleanup round 2:
  - retro_flash (3 files) → cartoons, tags: flash, 2000s, homestar_runner, strong_bad
  - scifi_tv (1 file) → tv_shows, tags: scifi, star_trek, comedy
  - skateboarding (1 file) → action, tag: skateboarding
  - philosophy_audio (2 files) → philosophy, tag: audio
Run on zikzak: python3 migrate_misc2.py
"""
import os, shutil, psycopg2, psycopg2.extras

pg = psycopg2.connect(os.environ["DATABASE_URL"])
cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
MEDIA = "/mnt/media"

# Create new folders and tags
cur.execute("""
    INSERT INTO categories (name, is_builtin, is_tag_only) VALUES
      ('action',          TRUE, FALSE),
      ('flash',           TRUE, TRUE),
      ('2000s',           TRUE, TRUE),
      ('homestar_runner', TRUE, TRUE),
      ('strong_bad',      TRUE, TRUE),
      ('scifi',           TRUE, TRUE),
      ('star_trek',       TRUE, TRUE),
      ('audio',           TRUE, TRUE),
      ('alan_watts',      TRUE, TRUE),
      ('mcluhan',         TRUE, TRUE)
    ON CONFLICT (name) DO NOTHING
""")

# file_id -> (dest_folder, dest_subdir, [tags], src_cat)
assignments = {
    # retro_flash → cartoons
    858: ("cartoons", "short", ["flash", "2000s", "homestar_runner", "strong_bad", "retro_flash"]),
    859: ("cartoons", "short", ["flash", "2000s", "homestar_runner", "strong_bad", "retro_flash"]),
    860: ("cartoons", "short", ["flash", "2000s", "homestar_runner", "strong_bad", "retro_flash"]),
    # scifi_tv → tv_shows
    873: ("tv_shows", "medium", ["scifi", "star_trek", "comedy", "scifi_tv"]),
    # skateboarding → action
    874: ("action", "long", ["skateboarding"]),
    # philosophy_audio → philosophy
    52:  ("philosophy", "short", ["audio", "alan_watts", "philosophy_audio"]),
    51:  ("philosophy", "long",  ["audio", "mcluhan", "philosophy_audio"]),
}

cur.execute("""
    SELECT id, category, subdir, filename FROM media_files
    WHERE category IN ('retro_flash', 'scifi_tv', 'skateboarding', 'philosophy_audio')
""")
files = {row["id"]: row for row in cur.fetchall()}

for fid, (dest, dest_subdir, tags) in assignments.items():
    f = files[fid]
    src = os.path.join(MEDIA, f["category"], f["subdir"], f["filename"])
    dst_dir = os.path.join(MEDIA, dest, dest_subdir)
    os.makedirs(dst_dir, exist_ok=True)
    if os.path.exists(src):
        shutil.move(src, os.path.join(dst_dir, f["filename"]))
        print(f"  {f['filename'][:60]} → {dest}/{dest_subdir}/")
    else:
        print(f"  WARN not found: {src}")

    cur.execute("UPDATE media_files SET category=%s, subdir=%s WHERE id=%s", (dest, dest_subdir, fid))
    cur.execute("""
        INSERT INTO media_file_categories (media_file_id, category_name, is_primary)
        VALUES (%s, %s, TRUE) ON CONFLICT DO NOTHING
    """, (fid, dest))
    for tag in tags:
        cur.execute("""
            INSERT INTO media_file_categories (media_file_id, category_name, is_primary)
            VALUES (%s, %s, FALSE) ON CONFLICT DO NOTHING
        """, (fid, tag))

# Retire old folders as tags
cur.execute("""
    UPDATE categories SET is_tag_only=TRUE
    WHERE name IN ('retro_flash', 'scifi_tv', 'skateboarding', 'philosophy_audio')
""")

# Remove empty dirs
for src_cat in ("retro_flash", "scifi_tv", "skateboarding", "philosophy_audio"):
    src_root = os.path.join(MEDIA, src_cat)
    for dp, _, _ in os.walk(src_root, topdown=False):
        if not os.listdir(dp):
            os.rmdir(dp)
    if os.path.isdir(src_root) and not os.listdir(src_root):
        os.rmdir(src_root)

pg.commit()
print("\nDone.")
for cat in ("cartoons", "tv_shows", "action", "philosophy"):
    cur.execute("SELECT COUNT(*) n FROM media_files WHERE category=%s", (cat,))
    print(f"  {cat}: {cur.fetchone()['n']} files")
cur.close()
pg.close()
