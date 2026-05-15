"""
Migrate gaming_memes → gaming:
  - Move files on disk: gaming_memes/bg3/[len]/ and gaming_memes/[len]/ → gaming/[len]/
  - Update media_files records
  - Populate media_file_categories (gaming tag for all; bg3 tag for bg3 files)
  - Rename gaming_memes → gaming in categories table
  - Update jobs table
Run on zikzak: python3 migrate_gaming_memes.py
"""
import os
import shutil
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ["DATABASE_URL"]
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/mnt/media")
SRC_CAT = "gaming_memes"
DST_CAT = "gaming"


def main():
    pg = psycopg2.connect(DATABASE_URL)
    pg.autocommit = False
    cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    src_root = os.path.join(MEDIA_ROOT, SRC_CAT)
    dst_root = os.path.join(MEDIA_ROOT, DST_CAT)
    os.makedirs(dst_root, exist_ok=True)

    # Collect all files under gaming_memes with their current subdir
    cur.execute(
        "SELECT id, subdir, filename FROM media_files WHERE category = %s",
        (SRC_CAT,)
    )
    files = cur.fetchall()
    print(f"Found {len(files)} media_files records under '{SRC_CAT}'")

    for f in files:
        fid = f["id"]
        old_subdir = f["subdir"]  # e.g. "bg3/short", "short", "medium"
        fname = f["filename"]
        is_bg3 = old_subdir.startswith("bg3")

        # Determine new subdir: strip "bg3/" prefix if present
        if is_bg3:
            new_subdir = old_subdir[len("bg3/"):]  # "bg3/short" → "short"
        else:
            new_subdir = old_subdir

        # Move the file
        src_path = os.path.join(src_root, old_subdir, fname) if old_subdir else os.path.join(src_root, fname)
        dst_dir = os.path.join(dst_root, new_subdir) if new_subdir else dst_root
        dst_path = os.path.join(dst_dir, fname)
        os.makedirs(dst_dir, exist_ok=True)

        if os.path.exists(src_path):
            shutil.move(src_path, dst_path)
            print(f"  moved: {old_subdir}/{fname} → {DST_CAT}/{new_subdir}/{fname}")
        else:
            print(f"  WARN: src not found: {src_path}")

        # Update media_files record
        cur.execute(
            "UPDATE media_files SET category = %s, subdir = %s WHERE id = %s",
            (DST_CAT, new_subdir, fid)
        )

        # Tag: gaming (primary) for all
        cur.execute(
            """INSERT INTO media_file_categories (media_file_id, category_name, is_primary)
               VALUES (%s, 'gaming', TRUE) ON CONFLICT DO NOTHING""",
            (fid,)
        )
        # Tag: bg3 for bg3-origin files
        if is_bg3:
            cur.execute(
                """INSERT INTO media_file_categories (media_file_id, category_name, is_primary)
                   VALUES (%s, 'bg3', FALSE) ON CONFLICT DO NOTHING""",
                (fid,)
            )

    # Rename category in categories table
    # First update any FK references in jobs
    cur.execute(
        "UPDATE jobs SET category = %s WHERE category = %s",
        (DST_CAT, SRC_CAT)
    )
    # Rename in categories (need to update media_files FK first — already done above)
    cur.execute("DELETE FROM categories WHERE name = %s", (SRC_CAT,))

    pg.commit()

    # Clean up empty dirs
    for dirpath, dirnames, filenames in os.walk(src_root, topdown=False):
        if not os.listdir(dirpath):
            os.rmdir(dirpath)
            print(f"  rmdir: {dirpath}")

    cur.execute(
        "SELECT COUNT(*) AS n FROM media_files WHERE category = %s", (DST_CAT,)
    )
    print(f"\nDone. {cur.fetchone()['n']} files now under '{DST_CAT}'")
    cur.execute(
        "SELECT COUNT(*) AS n FROM media_file_categories WHERE category_name = 'bg3'"
    )
    print(f"bg3 tags: {cur.fetchone()['n']}")

    cur.close()
    pg.close()


if __name__ == "__main__":
    main()
