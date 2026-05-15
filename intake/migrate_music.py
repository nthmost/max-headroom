"""
Migrate music categories → music:
  - aphex_twin, darkwave_postpunk, deep_techno, gaelic_resistance,
    house_music, metal, neon_synthpop, punk, vintage_music
  - Files move to /mnt/media/music/[length]/
  - Original category becomes a tag in media_file_categories
  - Original categories marked is_tag_only = TRUE
Run on zikzak: python3 migrate_music.py
"""
import os
import shutil
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ["DATABASE_URL"]
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/mnt/media")

MUSIC_CATS = [
    "aphex_twin", "darkwave_postpunk", "deep_techno", "gaelic_resistance",
    "house_music", "metal", "neon_synthpop", "punk", "vintage_music",
]
DST_CAT = "music"


def classify_length(secs):
    if not secs:
        return "medium"
    if secs < 300:
        return "short"
    if secs < 1800:
        return "medium"
    return "long"


def main():
    pg = psycopg2.connect(DATABASE_URL)
    pg.autocommit = False
    cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    dst_root = os.path.join(MEDIA_ROOT, DST_CAT)

    for src_cat in MUSIC_CATS:
        cur.execute(
            "SELECT id, subdir, filename, duration_secs FROM media_files WHERE category = %s",
            (src_cat,)
        )
        files = cur.fetchall()
        if not files:
            print(f"  {src_cat}: no files in DB, skipping")
            continue

        src_root = os.path.join(MEDIA_ROOT, src_cat)
        print(f"\n{src_cat} ({len(files)} files):")

        for f in files:
            fid = f["id"]
            old_subdir = f["subdir"]
            fname = f["filename"]

            # Use existing subdir if set, else classify from duration
            new_subdir = old_subdir if old_subdir else classify_length(f["duration_secs"])

            src_path = os.path.join(src_root, old_subdir, fname) if old_subdir else os.path.join(src_root, fname)
            dst_dir = os.path.join(dst_root, new_subdir)
            dst_path = os.path.join(dst_dir, fname)
            os.makedirs(dst_dir, exist_ok=True)

            if os.path.exists(src_path):
                shutil.move(src_path, dst_path)
                print(f"  moved → {DST_CAT}/{new_subdir}/{fname}")
            else:
                print(f"  WARN src not found: {src_path}")

            cur.execute(
                "UPDATE media_files SET category = %s, subdir = %s WHERE id = %s",
                (DST_CAT, new_subdir, fid)
            )
            # Primary tag: music
            cur.execute("""
                INSERT INTO media_file_categories (media_file_id, category_name, is_primary)
                VALUES (%s, 'music', TRUE) ON CONFLICT DO NOTHING
            """, (fid,))
            # Genre tag: original category
            cur.execute("""
                INSERT INTO media_file_categories (media_file_id, category_name, is_primary)
                VALUES (%s, %s, FALSE) ON CONFLICT DO NOTHING
            """, (fid, src_cat))

        # Mark original category as tag-only
        cur.execute(
            "UPDATE categories SET is_tag_only = TRUE WHERE name = %s",
            (src_cat,)
        )

    pg.commit()

    # Clean up empty source dirs
    for src_cat in MUSIC_CATS:
        src_root = os.path.join(MEDIA_ROOT, src_cat)
        for dirpath, dirnames, filenames in os.walk(src_root, topdown=False):
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
        if os.path.isdir(src_root) and not os.listdir(src_root):
            os.rmdir(src_root)

    cur.execute("SELECT COUNT(*) AS n FROM media_files WHERE category = 'music'")
    print(f"\nDone. {cur.fetchone()['n']} files under 'music'")
    cur.execute("""
        SELECT mfc.category_name, COUNT(*) AS n
        FROM media_file_categories mfc
        JOIN categories c ON c.name = mfc.category_name AND c.is_tag_only
        GROUP BY mfc.category_name ORDER BY mfc.category_name
    """)
    print("Genre tags:")
    for row in cur.fetchall():
        print(f"  {row['category_name']}: {row['n']}")

    cur.close()
    pg.close()


if __name__ == "__main__":
    main()
