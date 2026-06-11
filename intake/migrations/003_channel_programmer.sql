-- 003_channel_programmer.sql
-- Channel programming tables for the MHBN channel programmer UI.
-- Seed data reflects the known-working channels.liq as of 2026-06-11.

CREATE TABLE IF NOT EXISTS channel_configs (
    channel      TEXT PRIMARY KEY,
    label        TEXT NOT NULL,
    channel_type TEXT NOT NULL DEFAULT 'programmed',  -- 'music' | 'programmed'
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS channel_category_weights (
    id       SERIAL PRIMARY KEY,
    channel  TEXT NOT NULL REFERENCES channel_configs(channel) ON DELETE CASCADE,
    category TEXT NOT NULL,
    subdir   TEXT,          -- 'short' | 'medium' | 'long' | NULL (category root, e.g. prelinger)
    weight   INTEGER NOT NULL DEFAULT 1 CHECK (weight >= 1 AND weight <= 20),
    enabled  BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(channel, category, subdir)
);

-- ── Seed: channel configs ────────────────────────────────────────────────────

INSERT INTO channel_configs (channel, label, channel_type) VALUES
    ('ch1', 'Music',        'music'),
    ('ch2', 'Programmed A', 'programmed'),
    ('ch3', 'Programmed B', 'programmed'),
    ('ch4', 'Programmed C', 'programmed')
ON CONFLICT (channel) DO NOTHING;

-- ── Seed: ch2/ch3/ch4 weights (mirrors the hand-written channels.liq) ────────
-- Prelinger gets weight 5 (high variety, large archive, no short/medium/long).
-- Interstitials and commercials get weight 1 each (inserts).
-- All content categories start at weight 1 — adjust in the UI.

DO $$
DECLARE
    ch TEXT;
    weights TEXT[][] := ARRAY[
        ARRAY['anime',          'short',  '1'],
        ARRAY['cartoons',       'short',  '1'],
        ARRAY['cartoons',       'medium', '1'],
        ARRAY['comedy',         'short',  '1'],
        ARRAY['documentaries',  'short',  '1'],
        ARRAY['gaming',         'short',  '1'],
        ARRAY['gaming',         'medium', '1'],
        ARRAY['philosophy',     'short',  '1'],
        ARRAY['philosophy',     'medium', '1'],
        ARRAY['tv_shows',       'short',  '1'],
        ARRAY['tv_shows',       'medium', '1'],
        ARRAY['prelinger',      NULL,     '5'],
        ARRAY['interstitials',  NULL,     '1'],
        ARRAY['commercials',    'short',  '1']
    ];
    row TEXT[];
BEGIN
    FOREACH ch IN ARRAY ARRAY['ch2', 'ch3', 'ch4'] LOOP
        FOREACH row SLICE 1 IN ARRAY weights LOOP
            INSERT INTO channel_category_weights (channel, category, subdir, weight)
            VALUES (ch, row[1], row[2], row[3]::INTEGER)
            ON CONFLICT (channel, category, subdir) DO NOTHING;
        END LOOP;
    END LOOP;
END $$;
