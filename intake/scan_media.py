"""
Scan /mnt/media into the media_files table.
Runs on zikzak: python3 scan_media.py
Uses ffprobe for duration/resolution/bitrate.
subdir stores the full relative path from the category root (e.g. "short",
"bg3/short", or "" for bare files directly in the category dir).
"""
import os
import json
import subprocess
import psycopg2

DATABASE_URL = os.environ["DATABASE_URL"]
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/mnt/media")
EXTENSIONS = (".mp4", ".mkv", ".avi", ".webm")


def ffprobe(path):
    try:
        result = subprocess.run([
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", path,
        ], capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout)
    except Exception:
        return {}
    fmt = data.get("format", {})
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    duration = None
    for src in (fmt, video):
        try:
            duration = float(src.get("duration") or 0) or None
            if duration:
                break
        except (ValueError, TypeError):
            pass
    try:
        bitrate = int(fmt.get("bit_rate", 0)) // 1000 or None
    except (ValueError, TypeError):
        bitrate = None
    return {
        "duration_secs": duration,
        "width": video.get("width"),
        "height": video.get("height"),
        "bitrate_kbps": bitrate,
    }


def main():
    pg = psycopg2.connect(DATABASE_URL)
    cur = pg.cursor()

    inserted = errors = 0
    for category in sorted(os.listdir(MEDIA_ROOT)):
        cat_path = os.path.join(MEDIA_ROOT, category)
        if not os.path.isdir(cat_path) or category.startswith("lost+"):
            continue
        for dirpath, dirnames, filenames in os.walk(cat_path):
            dirnames.sort()
            rel = os.path.relpath(dirpath, cat_path)
            subdir = "" if rel == "." else rel
            for fname in sorted(filenames):
                if not fname.lower().endswith(EXTENSIONS):
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    filesize = os.path.getsize(fpath)
                    meta = ffprobe(fpath)
                    cur.execute("""
                        INSERT INTO media_files
                            (category, subdir, filename, filesize_bytes,
                             duration_secs, width, height, bitrate_kbps)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (category, subdir, filename) DO NOTHING
                    """, (
                        category, subdir, fname, filesize,
                        meta.get("duration_secs"), meta.get("width"),
                        meta.get("height"), meta.get("bitrate_kbps"),
                    ))
                    inserted += 1
                    if inserted % 50 == 0:
                        pg.commit()
                        print(f"  {inserted} files...", flush=True)
                except Exception as e:
                    print(f"  ERROR {fpath}: {e}", flush=True)
                    errors += 1

    pg.commit()
    cur.execute("SELECT COUNT(*) FROM media_files")
    total = cur.fetchone()[0]
    print(f"Done. {inserted} attempted, {errors} errors. Total in DB: {total}", flush=True)
    cur.close()
    pg.close()


if __name__ == "__main__":
    main()
