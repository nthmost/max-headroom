"""
Rename joke_commercials → commercials, tag files with comedy.
Run on zikzak: python3 migrate_commercials.py
"""
import os, shutil, psycopg2, psycopg2.extras

pg = psycopg2.connect(os.environ["DATABASE_URL"])
cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
MEDIA = "/mnt/media"

cur.execute("INSERT INTO categories (name, is_builtin, is_tag_only) VALUES ('commercials', TRUE, FALSE) ON CONFLICT DO NOTHING")

cur.execute("SELECT id, subdir, filename FROM media_files WHERE category='joke_commercials'")
files = cur.fetchall()
print(f"joke_commercials ({len(files)} files):")

for f in files:
    src = os.path.join(MEDIA, "joke_commercials", f["subdir"], f["filename"])
    dst_dir = os.path.join(MEDIA, "commercials", f["subdir"])
    os.makedirs(dst_dir, exist_ok=True)
    if os.path.exists(src):
        shutil.move(src, os.path.join(dst_dir, f["filename"]))
        print(f"  → commercials/{f['subdir']}/{f['filename']}")
    else:
        print(f"  WARN not found: {src}")

    cur.execute("UPDATE media_files SET category='commercials' WHERE id=%s", (f["id"],))
    cur.execute("""
        INSERT INTO media_file_categories (media_file_id, category_name, is_primary) VALUES
          (%s, 'commercials', TRUE),
          (%s, 'comedy', FALSE),
          (%s, 'joke_commercials', FALSE)
        ON CONFLICT DO NOTHING
    """, (f["id"], f["id"], f["id"]))

cur.execute("UPDATE categories SET is_tag_only=TRUE WHERE name='joke_commercials'")

src_root = os.path.join(MEDIA, "joke_commercials")
for dp, _, _ in os.walk(src_root, topdown=False):
    if not os.listdir(dp):
        os.rmdir(dp)
if os.path.isdir(src_root) and not os.listdir(src_root):
    os.rmdir(src_root)

pg.commit()
print(f"\nDone. commercials folder ready.")
cur.close()
pg.close()
