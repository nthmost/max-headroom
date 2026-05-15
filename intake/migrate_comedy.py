"""
Merge british_surreal_comedy, sketch_comedy, retro_sketch_comedy → comedy
Run on zikzak: python3 migrate_comedy.py
"""
import os, shutil, psycopg2, psycopg2.extras

pg = psycopg2.connect(os.environ["DATABASE_URL"])
cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
MEDIA = "/mnt/media"
SRC_CATS = ["british_surreal_comedy", "sketch_comedy", "retro_sketch_comedy"]
DST_CAT = "comedy"

cur.execute("INSERT INTO categories (name,is_builtin) VALUES (%s,TRUE) ON CONFLICT DO NOTHING", (DST_CAT,))

for src_cat in SRC_CATS:
    cur.execute("SELECT id, subdir, filename FROM media_files WHERE category=%s", (src_cat,))
    files = cur.fetchall()
    src_root = os.path.join(MEDIA, src_cat)
    print(f"{src_cat} ({len(files)} files):")
    for f in files:
        src = os.path.join(src_root, f["subdir"], f["filename"])
        dst_dir = os.path.join(MEDIA, DST_CAT, f["subdir"])
        os.makedirs(dst_dir, exist_ok=True)
        if os.path.exists(src):
            shutil.move(src, os.path.join(dst_dir, f["filename"]))
            print(f"  → {DST_CAT}/{f['subdir']}/{f['filename']}")
        else:
            print(f"  WARN not found: {src}")
        cur.execute("UPDATE media_files SET category=%s WHERE id=%s", (DST_CAT, f["id"]))
        cur.execute("INSERT INTO media_file_categories VALUES (%s,%s,TRUE) ON CONFLICT DO NOTHING", (f["id"], DST_CAT))
        cur.execute("INSERT INTO media_file_categories VALUES (%s,%s,FALSE) ON CONFLICT DO NOTHING", (f["id"], src_cat))

    cur.execute("UPDATE categories SET is_tag_only=TRUE WHERE name=%s", (src_cat,))
    for dp, _, _ in os.walk(src_root, topdown=False):
        if not os.listdir(dp):
            os.rmdir(dp)
    if os.path.isdir(src_root) and not os.listdir(src_root):
        os.rmdir(src_root)

pg.commit()
cur.execute("SELECT COUNT(*) AS n FROM media_files WHERE category='comedy'")
print(f"\nTotal comedy files: {cur.fetchone()['n']}")
cur.close()
pg.close()
