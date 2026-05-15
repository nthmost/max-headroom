"""
Tag all prelinger files with their collection subdir name.
Each subdir (atomic, noir, 1970s, etc.) becomes a tag-only category
and is applied to every file in that collection.
Run on zikzak: python3 tag_prelinger.py
"""
import os, psycopg2, psycopg2.extras

pg = psycopg2.connect(os.environ["DATABASE_URL"])
cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# Get all distinct non-empty subdirs
cur.execute("""
    SELECT DISTINCT subdir FROM media_files
    WHERE category = 'prelinger' AND subdir IS NOT NULL AND subdir != ''
    ORDER BY subdir
""")
subdirs = [r["subdir"] for r in cur.fetchall()]
print(f"Collections to tag: {subdirs}\n")

# Create all collection tags
for tag in subdirs:
    cur.execute("""
        INSERT INTO categories (name, is_builtin, is_tag_only)
        VALUES (%s, TRUE, TRUE)
        ON CONFLICT DO NOTHING
    """, (tag,))

# Ensure prelinger itself is tagged as primary on all files
cur.execute("SELECT id, subdir FROM media_files WHERE category = 'prelinger'")
files = cur.fetchall()

tagged = 0
for f in files:
    cur.execute("""
        INSERT INTO media_file_categories (media_file_id, category_name, is_primary)
        VALUES (%s, 'prelinger', TRUE)
        ON CONFLICT DO NOTHING
    """, (f["id"],))
    if f["subdir"]:
        cur.execute("""
            INSERT INTO media_file_categories (media_file_id, category_name, is_primary)
            VALUES (%s, %s, FALSE)
            ON CONFLICT DO NOTHING
        """, (f["id"], f["subdir"]))
        tagged += 1

pg.commit()
print(f"Tagged {tagged} files with collection tags.")
print(f"Skipped {len(files) - tagged} files with no subdir.")

cur.execute("""
    SELECT mfc.category_name, COUNT(*) AS n
    FROM media_file_categories mfc
    JOIN categories c ON c.name = mfc.category_name AND c.is_tag_only
    WHERE mfc.category_name IN (SELECT DISTINCT subdir FROM media_files WHERE category='prelinger' AND subdir != '')
    GROUP BY mfc.category_name ORDER BY n DESC
""")
print("\nCollection tag counts:")
for row in cur.fetchall():
    print(f"  {row['category_name']}: {row['n']}")

cur.close()
pg.close()
