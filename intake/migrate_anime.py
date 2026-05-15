"""
Consolidate anime categories → anime:
  - cyberpunk_anime (3 files) → anime/short/, tags: cyberpunk
  - retro_anime (1 file) → anime/short/, tags: retro
  - cyberpunk becomes a real top-level category (is_tag_only=FALSE)
Run on zikzak: python3 migrate_anime.py
"""
import os, shutil, psycopg2, psycopg2.extras

pg = psycopg2.connect(os.environ["DATABASE_URL"])
cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
MEDIA = "/mnt/media"

# Ensure destination categories exist
cur.execute("""
    INSERT INTO categories (name, is_builtin, is_tag_only) VALUES
      ('anime',    TRUE, FALSE),
      ('cyberpunk', TRUE, TRUE),
      ('retro',    TRUE, TRUE)
    ON CONFLICT (name) DO UPDATE SET is_builtin = EXCLUDED.is_builtin
""")

migrations = [
    # (src_cat, extra_tags)
    ("cyberpunk_anime", ["cyberpunk"]),
    ("retro_anime",     ["retro"]),
]

for src_cat, extra_tags in migrations:
    cur.execute("SELECT id, subdir, filename FROM media_files WHERE category=%s", (src_cat,))
    files = cur.fetchall()
    print(f"\n{src_cat} ({len(files)} files):")

    for f in files:
        src = os.path.join(MEDIA, src_cat, f["subdir"], f["filename"])
        dst_dir = os.path.join(MEDIA, "anime", f["subdir"])
        os.makedirs(dst_dir, exist_ok=True)

        if os.path.exists(src):
            shutil.move(src, os.path.join(dst_dir, f["filename"]))
            print(f"  → anime/{f['subdir']}/{f['filename']}")
        else:
            print(f"  WARN not found: {src}")

        cur.execute("UPDATE media_files SET category='anime' WHERE id=%s", (f["id"],))
        cur.execute("""
            INSERT INTO media_file_categories (media_file_id, category_name, is_primary)
            VALUES (%s, 'anime', TRUE) ON CONFLICT DO NOTHING
        """, (f["id"],))
        cur.execute("""
            INSERT INTO media_file_categories (media_file_id, category_name, is_primary)
            VALUES (%s, %s, FALSE) ON CONFLICT DO NOTHING
        """, (f["id"], src_cat))
        for tag in extra_tags:
            cur.execute("""
                INSERT INTO media_file_categories (media_file_id, category_name, is_primary)
                VALUES (%s, %s, FALSE) ON CONFLICT DO NOTHING
            """, (f["id"], tag))

    cur.execute("UPDATE categories SET is_tag_only=TRUE WHERE name=%s", (src_cat,))

    src_root = os.path.join(MEDIA, src_cat)
    for dp, _, _ in os.walk(src_root, topdown=False):
        if not os.listdir(dp):
            os.rmdir(dp)
    if os.path.isdir(src_root) and not os.listdir(src_root):
        os.rmdir(src_root)

pg.commit()

cur.execute("SELECT COUNT(*) AS n FROM media_files WHERE category='anime'")
print(f"\nTotal anime files: {cur.fetchone()['n']}")
cur.close()
pg.close()
