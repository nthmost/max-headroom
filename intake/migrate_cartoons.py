"""
Consolidate into cartoons folder:
  - adult_swim (1 file) → cartoons/short/, tag: adult_swim
  - liquid_television (2 files) → cartoons/[length]/, tag: liquid_television
Run on zikzak: python3 migrate_cartoons.py
"""
import os, shutil, psycopg2, psycopg2.extras

pg = psycopg2.connect(os.environ["DATABASE_URL"])
cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
MEDIA = "/mnt/media"

cur.execute("""
    INSERT INTO categories (name, is_builtin, is_tag_only) VALUES ('cartoons', TRUE, FALSE)
    ON CONFLICT DO NOTHING
""")

for src_cat in ("adult_swim", "liquid_television"):
    cur.execute("SELECT id, subdir, filename FROM media_files WHERE category=%s", (src_cat,))
    files = cur.fetchall()
    print(f"\n{src_cat} ({len(files)} files):")

    for f in files:
        src = os.path.join(MEDIA, src_cat, f["subdir"], f["filename"])
        dst_dir = os.path.join(MEDIA, "cartoons", f["subdir"])
        os.makedirs(dst_dir, exist_ok=True)

        if os.path.exists(src):
            shutil.move(src, os.path.join(dst_dir, f["filename"]))
            print(f"  → cartoons/{f['subdir']}/{f['filename']}")
        else:
            print(f"  WARN not found: {src}")

        cur.execute("UPDATE media_files SET category='cartoons' WHERE id=%s", (f["id"],))
        cur.execute("""
            INSERT INTO media_file_categories (media_file_id, category_name, is_primary)
            VALUES (%s, 'cartoons', TRUE) ON CONFLICT DO NOTHING
        """, (f["id"],))
        cur.execute("""
            INSERT INTO media_file_categories (media_file_id, category_name, is_primary)
            VALUES (%s, %s, FALSE) ON CONFLICT DO NOTHING
        """, (f["id"], src_cat))

    cur.execute("UPDATE categories SET is_tag_only=TRUE WHERE name=%s", (src_cat,))

    src_root = os.path.join(MEDIA, src_cat)
    for dp, _, _ in os.walk(src_root, topdown=False):
        if not os.listdir(dp):
            os.rmdir(dp)
    if os.path.isdir(src_root) and not os.listdir(src_root):
        os.rmdir(src_root)

pg.commit()

cur.execute("SELECT COUNT(*) AS n FROM media_files WHERE category='cartoons'")
print(f"\nTotal cartoons files: {cur.fetchone()['n']}")
cur.close()
pg.close()
