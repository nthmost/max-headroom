"""
Cross-check DB media_files against actual files on disk.
Reports:
  - DB records with no corresponding file on disk
  - Files on disk not registered in the DB
Run on zikzak: python3 integrity_check.py
"""
import os, psycopg2, psycopg2.extras

MEDIA = os.environ.get("MEDIA_ROOT", "/mnt/media")
pg = psycopg2.connect(os.environ["DATABASE_URL"])
cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# --- DB records ---
cur.execute("SELECT id, category, subdir, filename FROM media_files WHERE is_active IS DISTINCT FROM FALSE ORDER BY category, subdir, filename")
db_files = cur.fetchall()

db_paths = {}
for row in db_files:
    rel = os.path.join(row["category"], row["subdir"] or "", row["filename"])
    db_paths[rel] = row

# --- Disk files ---
EXTS = {".mp4", ".webm", ".mkv", ".ogv", ".avi"}
disk_paths = set()
for dirpath, dirnames, filenames in os.walk(MEDIA):
    # skip lost+found and hidden dirs
    dirnames[:] = [d for d in dirnames if not d.startswith("lost+") and not d.startswith(".")]
    for fname in filenames:
        if os.path.splitext(fname)[1].lower() in EXTS:
            rel = os.path.relpath(os.path.join(dirpath, fname), MEDIA)
            disk_paths.add(rel)

# --- Compare ---
db_set   = set(db_paths.keys())
only_db  = db_set - disk_paths    # in DB, missing on disk
only_disk = disk_paths - db_set   # on disk, not in DB

print(f"DB records:   {len(db_set)}")
print(f"Disk files:   {len(disk_paths)}")
print()

if only_db:
    print(f"=== IN DB BUT MISSING ON DISK ({len(only_db)}) ===")
    for p in sorted(only_db):
        row = db_paths[p]
        print(f"  [id={row['id']}] {p}")
else:
    print("✓ No DB records missing from disk")

print()

if only_disk:
    print(f"=== ON DISK BUT NOT IN DB ({len(only_disk)}) ===")
    for p in sorted(only_disk):
        print(f"  {p}")
else:
    print("✓ No disk files missing from DB")

cur.close()
pg.close()
