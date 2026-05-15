"""
One-shot migration: SQLite → Postgres.
Seeds categories from on-disk dirs + user_categories, migrates jobs.
Run once from loki: python3 migrate_to_pg.py
"""
import os
import sqlite3
import psycopg2
import psycopg2.extras

SQLITE_PATH = os.path.join(os.path.dirname(__file__), "intake.db")
DATABASE_URL = os.environ["DATABASE_URL"]
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/mnt/media")

BUILTIN_CATEGORIES = [
    "british_surreal_comedy", "comic_memes", "cyberpunk_anime", "cyberpunk_memes",
    "darkwave_postpunk", "deep_techno", "fantasy_memes", "gaelic_resistance",
    "gaming_memes", "house_music", "interstitials", "joke_commercials",
    "joke_documentaries", "neon_synthpop", "philosophy", "philosophy_audio",
    "prelinger", "retro_anime", "retro_flash", "retro_mashups",
    "retro_sketch_comedy", "scifi_tv", "sketch_comedy", "surreal_talkshows",
    "vintage_talkshows",
]

def main():
    pg = psycopg2.connect(DATABASE_URL)
    pg.autocommit = False
    cur = pg.cursor()

    sq = sqlite3.connect(SQLITE_PATH)
    sq.row_factory = sqlite3.Row

    # --- Categories ---
    # 1. Builtin list
    for name in BUILTIN_CATEGORIES:
        cur.execute(
            "INSERT INTO categories (name, is_builtin) VALUES (%s, TRUE) ON CONFLICT DO NOTHING",
            (name,)
        )

    # 2. On-disk dirs not in builtin list
    try:
        disk_cats = {d for d in os.listdir(MEDIA_ROOT)
                     if os.path.isdir(os.path.join(MEDIA_ROOT, d))
                     and not d.startswith("lost+")}
    except FileNotFoundError:
        disk_cats = set()
        print(f"Warning: MEDIA_ROOT {MEDIA_ROOT!r} not found, skipping disk scan for categories")

    for name in sorted(disk_cats - set(BUILTIN_CATEGORIES)):
        cur.execute(
            "INSERT INTO categories (name, is_builtin) VALUES (%s, FALSE) ON CONFLICT DO NOTHING",
            (name,)
        )
        print(f"  added non-builtin category from disk: {name}")

    # 3. user_categories from SQLite (mark as non-builtin)
    for row in sq.execute("SELECT name, created_at FROM user_categories"):
        cur.execute(
            """INSERT INTO categories (name, is_builtin, created_at)
               VALUES (%s, FALSE, %s::timestamptz)
               ON CONFLICT (name) DO UPDATE SET is_builtin = FALSE""",
            (row["name"], row["created_at"])
        )

    # --- Jobs ---
    jobs = sq.execute("SELECT * FROM jobs").fetchall()
    for j in jobs:
        cur.execute("""
            INSERT INTO jobs (
                id, created_at, url, title, source, category, length,
                status, pid, log_path, error_msg, updated_at,
                pipeline_status, phase, crop_sides, filename
            ) VALUES (
                %s, %s::timestamptz, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s::timestamptz,
                %s, %s, %s, %s
            ) ON CONFLICT (id) DO NOTHING
        """, (
            j["id"], j["created_at"], j["url"], j["title"], j["source"],
            j["category"], j["length"], j["status"], j["pid"], j["log_path"],
            j["error_msg"], j["updated_at"], j["pipeline_status"],
            j["phase"] if "phase" in j.keys() else None, bool(j["crop_sides"]), j["filename"],
        ))

    # Reset sequence to max id
    cur.execute("SELECT setval('jobs_id_seq', COALESCE(MAX(id), 1)) FROM jobs")

    pg.commit()

    cur.execute("SELECT COUNT(*) FROM categories")
    print(f"Categories: {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM jobs")
    print(f"Jobs migrated: {cur.fetchone()[0]}")

    cur.close()
    pg.close()
    sq.close()
    print("Done.")

if __name__ == "__main__":
    main()
