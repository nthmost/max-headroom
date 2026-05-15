"""
Collapse surreal_talkshows + vintage_talkshows:
  - Space Ghost → cartoons, tags: adult_swim, space_ghost, talkshow, surreal
  - Rick & Morty → cartoons, tags: adult_swim, rick_and_morty, surreal
  - Henry Killinger → cartoons, tags: adult_swim, venture_bros
  - Muppet Show → cartoons, tags: talkshow, muppets, vintage
  - Jonathan Frakes → tv_shows, tags: talkshow, surreal, beyond_belief
  - Hunter S. Thompson + Björk/Conan → tv_shows, tags: talkshow, vintage, conan (HST also standalone)
Run on zikzak: python3 migrate_talkshows.py
"""
import os, shutil, psycopg2, psycopg2.extras

pg = psycopg2.connect(os.environ["DATABASE_URL"])
cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
MEDIA = "/mnt/media"

# Create new tags and tv_shows folder
cur.execute("""
    INSERT INTO categories (name, is_builtin, is_tag_only) VALUES
      ('tv_shows',      TRUE, FALSE),
      ('talkshow',      TRUE, TRUE),
      ('surreal',       TRUE, TRUE),
      ('vintage',       TRUE, TRUE),
      ('space_ghost',   TRUE, TRUE),
      ('rick_and_morty',TRUE, TRUE),
      ('venture_bros',  TRUE, TRUE),
      ('muppets',       TRUE, TRUE),
      ('beyond_belief', TRUE, TRUE),
      ('conan',         TRUE, TRUE)
    ON CONFLICT (name) DO NOTHING
""")

# file_id -> (dest_folder, [tags])
assignments = {
    # Space Ghost
    877: ("cartoons", ["adult_swim", "space_ghost", "talkshow", "surreal"]),
    878: ("cartoons", ["adult_swim", "space_ghost", "talkshow", "surreal"]),
    879: ("cartoons", ["adult_swim", "space_ghost", "surreal"]),
    880: ("cartoons", ["adult_swim", "space_ghost", "talkshow", "surreal"]),
    890: ("cartoons", ["adult_swim", "space_ghost", "talkshow", "surreal"]),
    894: ("cartoons", ["adult_swim", "space_ghost", "talkshow", "surreal"]),
    895: ("cartoons", ["adult_swim", "space_ghost", "talkshow", "surreal"]),
    # Rick & Morty
    881: ("cartoons", ["adult_swim", "rick_and_morty", "surreal"]),
    882: ("cartoons", ["adult_swim", "rick_and_morty", "surreal"]),
    884: ("cartoons", ["adult_swim", "rick_and_morty", "surreal"]),
    885: ("cartoons", ["adult_swim", "rick_and_morty", "surreal"]),
    886: ("cartoons", ["adult_swim", "rick_and_morty", "surreal"]),
    891: ("cartoons", ["adult_swim", "rick_and_morty", "surreal"]),
    892: ("cartoons", ["adult_swim", "rick_and_morty", "surreal"]),
    893: ("cartoons", ["adult_swim", "rick_and_morty", "surreal"]),
    896: ("cartoons", ["adult_swim", "rick_and_morty", "surreal"]),
    897: ("cartoons", ["adult_swim", "rick_and_morty", "surreal"]),
    # Venture Bros
    883: ("cartoons", ["adult_swim", "venture_bros"]),
    # Jonathan Frakes
    887: ("tv_shows", ["talkshow", "surreal", "beyond_belief"]),
    888: ("tv_shows", ["talkshow", "surreal", "beyond_belief"]),
    889: ("tv_shows", ["talkshow", "surreal", "beyond_belief"]),
    # Muppet Show
    902: ("cartoons", ["talkshow", "muppets", "vintage"]),
    # Hunter S. Thompson
    899: ("tv_shows", ["talkshow", "vintage"]),
    900: ("tv_shows", ["talkshow", "vintage", "conan"]),
    # Björk on Conan
    901: ("tv_shows", ["talkshow", "vintage", "conan"]),
}

cur.execute("""
    SELECT id, category, subdir, filename FROM media_files
    WHERE category IN ('surreal_talkshows', 'vintage_talkshows')
""")
files = {row["id"]: row for row in cur.fetchall()}

for fid, (dest, tags) in assignments.items():
    f = files[fid]
    src = os.path.join(MEDIA, f["category"], f["subdir"], f["filename"])
    dst_dir = os.path.join(MEDIA, dest, f["subdir"])
    os.makedirs(dst_dir, exist_ok=True)
    if os.path.exists(src):
        shutil.move(src, os.path.join(dst_dir, f["filename"]))
        print(f"  {f['filename'][:60]} → {dest}/{f['subdir']}/")
    else:
        print(f"  WARN not found: {src}")

    cur.execute("UPDATE media_files SET category=%s WHERE id=%s", (dest, fid))
    cur.execute("""
        INSERT INTO media_file_categories (media_file_id, category_name, is_primary)
        VALUES (%s, %s, TRUE) ON CONFLICT DO NOTHING
    """, (fid, dest))
    # legacy source tag
    cur.execute("""
        INSERT INTO media_file_categories (media_file_id, category_name, is_primary)
        VALUES (%s, %s, FALSE) ON CONFLICT DO NOTHING
    """, (fid, f["category"]))
    for tag in tags:
        cur.execute("""
            INSERT INTO media_file_categories (media_file_id, category_name, is_primary)
            VALUES (%s, %s, FALSE) ON CONFLICT DO NOTHING
        """, (fid, tag))

cur.execute("UPDATE categories SET is_tag_only=TRUE WHERE name IN ('surreal_talkshows','vintage_talkshows')")

for src_cat in ("surreal_talkshows", "vintage_talkshows"):
    src_root = os.path.join(MEDIA, src_cat)
    for dp, _, _ in os.walk(src_root, topdown=False):
        if not os.listdir(dp):
            os.rmdir(dp)
    if os.path.isdir(src_root) and not os.listdir(src_root):
        os.rmdir(src_root)

pg.commit()
print(f"\nDone.")
cur.execute("SELECT category, COUNT(*) n FROM media_files WHERE category IN ('cartoons','tv_shows') GROUP BY category ORDER BY category")
for row in cur.fetchall():
    print(f"  {row['category']}: {row['n']} files")
cur.close()
pg.close()
