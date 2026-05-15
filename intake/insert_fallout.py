import os, json, subprocess, psycopg2

pg = psycopg2.connect(os.environ["DATABASE_URL"])
cur = pg.cursor()

files = [
    ("gaming", "short",  "Fallout_4_S.P.E.C.I.A.L._Video_Series_-_Strength.mkv"),
    ("gaming", "short",  "Fallout_4_S.P.E.C.I.A.L._Video_Series_-_Charisma.mkv"),
    ("gaming", "medium", "Fallout_4_S.P.E.C.I.A.L._Video_Series_-_Charisma.mkv"),
]

for cat, subdir, fname in files:
    path = f"/mnt/media/{cat}/{subdir}/{fname}"
    r = subprocess.run(["ffprobe","-v","quiet","-print_format","json","-show_streams","-show_format",path],
                       capture_output=True, text=True, timeout=30)
    d = json.loads(r.stdout)
    fmt = d.get("format", {})
    vid = next((s for s in d.get("streams",[]) if s.get("codec_type")=="video"), {})
    dur = None
    for src in (fmt, vid):
        try:
            dur = float(src.get("duration") or 0) or None
            if dur: break
        except: pass
    bps = int(fmt.get("bit_rate", 0)) // 1000 or None
    size = os.path.getsize(path)
    cur.execute("""
        INSERT INTO media_files (category, subdir, filename, filesize_bytes, duration_secs, width, height, bitrate_kbps)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id
    """, (cat, subdir, fname, size, dur, vid.get("width"), vid.get("height"), bps))
    row = cur.fetchone()
    if row:
        fid = row[0]
        cur.execute("INSERT INTO media_file_categories (media_file_id, category_name, is_primary) VALUES (%s,'gaming',TRUE) ON CONFLICT DO NOTHING", (fid,))
        print(f"inserted id={fid}: {subdir}/{fname}")
    else:
        print(f"conflict (exists): {subdir}/{fname}")

pg.commit()
cur.execute("SELECT COUNT(*) FROM media_files WHERE category='gaming'")
print(f"Total gaming files: {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM media_file_categories WHERE category_name='bg3'")
print(f"bg3 tags: {cur.fetchone()[0]}")
pg.close()
