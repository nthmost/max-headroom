"""
Rename joke_documentaries → documentaries, tag files with comedy.
Run on zikzak: python3 migrate_documentaries.py
"""
import os, shutil, psycopg2, psycopg2.extras

pg = psycopg2.connect(os.environ["DATABASE_URL"])
cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
MEDIA = "/mnt/media"

cur.execute("INSERT INTO categories (name, is_builtin, is_tag_only) VALUES ('documentaries', TRUE, FALSE) ON CONFLICT DO NOTHING")

cur.execute("SELECT id, subdir, filename FROM media_files WHERE category='joke_documentaries'")
files = cur.fetchall()
print(f"joke_documentaries ({len(files)} files):")

for f in files:
    src = os.path.join(MEDIA, "joke_documentaries", f["subdir"], f["filename"])
    dst_dir = os.path.join(MEDIA, "documentaries", f["subdir"])
    os.makedirs(dst_dir, exist_ok=True)
    if os.path.exists(src):
        shutil.move(src, os.path.join(dst_dir, f["filename"]))
        print(f"  → documentaries/{f['subdir']}/{f['filename']}")
    else:
        print(f"  WARN not found: {src}")

    cur.execute("UPDATE media_files SET category='documentaries' WHERE id=%s", (f["id"],))
    cur.execute("""
        INSERT INTO media_file_categories (media_file_id, category_name, is_primary) VALUES
          (%s, 'documentaries', TRUE),
          (%s, 'comedy', FALSE),
          (%s, 'joke_documentaries', FALSE)
        ON CONFLICT DO NOTHING
    """, (f["id"], f["id"], f["id"]))

cur.execute("UPDATE categories SET is_tag_only=TRUE WHERE name='joke_documentaries'")

src_root = os.path.join(MEDIA, "joke_documentaries")
for dp, _, _ in os.walk(src_root, topdown=False):
    if not os.listdir(dp):
        os.rmdir(dp)
if os.path.isdir(src_root) and not os.listdir(src_root):
    os.rmdir(src_root)

pg.commit()
print("Done.")
cur.close()
pg.close()
