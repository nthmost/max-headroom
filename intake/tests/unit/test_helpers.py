"""Tests for the pure helpers in downloader.py and analyzer.py."""

import os
import re

import analyzer
import downloader


# ─── downloader._yt_restrict ────────────────────────────────────────────────

def test_yt_restrict_strips_specials():
    # Approximates yt-dlp --restrict-filenames: spaces and punct become _.
    assert downloader._yt_restrict("Hello World!") == "Hello_World_"
    assert downloader._yt_restrict("a/b/c") == "a_b_c"


def test_yt_restrict_preserves_dot_hyphen_word():
    # Dots, hyphens, alphanumerics, and underscores survive.
    assert downloader._yt_restrict("foo-bar.baz_qux") == "foo-bar.baz_qux"


# ─── downloader.parse_ia_identifier ─────────────────────────────────────────

def test_parse_ia_identifier_from_details_url():
    assert downloader.parse_ia_identifier(
        "https://archive.org/details/Popeye_forPresident"
    ) == "Popeye_forPresident"


def test_parse_ia_identifier_from_bare():
    assert downloader.parse_ia_identifier("Popeye_forPresident") == "Popeye_forPresident"


def test_parse_ia_identifier_strips_whitespace_in_bare():
    assert downloader.parse_ia_identifier("  prelinger-1953  ") == "prelinger-1953"


def test_parse_ia_identifier_rejects_invalid():
    assert downloader.parse_ia_identifier("https://example.com/whatever") is None
    assert downloader.parse_ia_identifier("not a valid id with spaces") is None


# ─── downloader._ia_first_length ────────────────────────────────────────────

def test_ia_first_length_picks_first_parseable():
    files = [
        {"name": "thumb.png"},                # no length
        {"name": "video.mp4", "length": "152.4"},
        {"name": "fallback.mp4", "length": "60"},
    ]
    assert downloader._ia_first_length(files) == 152


def test_ia_first_length_skips_unparseable():
    files = [
        {"name": "video.mp4", "length": "not-a-number"},
        {"name": "other.mp4", "length": "42"},
    ]
    assert downloader._ia_first_length(files) == 42


def test_ia_first_length_returns_none_when_no_lengths():
    assert downloader._ia_first_length([{"name": "thumb.png"}]) is None
    assert downloader._ia_first_length([]) is None


# ─── downloader._empty_ia_metadata ──────────────────────────────────────────

def test_empty_ia_metadata_shape():
    result = downloader._empty_ia_metadata("foo")
    # Stable contract — consumers depend on these keys.
    assert set(result) == {
        "title", "duration_seconds", "description", "tags", "channel", "uploader"
    }
    assert result["title"] == "foo"
    assert result["duration_seconds"] is None
    assert result["tags"] == []


# ─── downloader._dropbox_paths ──────────────────────────────────────────────

def test_dropbox_paths_format():
    incoming, rejected = downloader._dropbox_paths(42, "foo.mp4")
    assert incoming.endswith("/42__foo.mp4")
    assert rejected.endswith("/rejected/42__foo.mp4")


# ─── downloader._purge_glob_for ─────────────────────────────────────────────

def test_purge_glob_for_uses_filename_when_present():
    job = {"filename": "thing.mp4", "title": "Some Title"}
    assert downloader._purge_glob_for(job) == "thing.mp4"


def test_purge_glob_for_falls_back_to_title_glob():
    job = {"filename": None, "title": "Some Title"}
    assert downloader._purge_glob_for(job) == "Some_Title.*"


def test_purge_glob_for_returns_none_when_no_clues():
    assert downloader._purge_glob_for({"filename": None, "title": ""}) is None
    assert downloader._purge_glob_for({"filename": None}) is None


# ─── downloader._ia_local_dirs ──────────────────────────────────────────────

def test_ia_local_dirs_uses_incoming_and_transcoded():
    incoming, transcoded = downloader._ia_local_dirs("documentaries", "long")
    assert incoming.endswith("/documentaries/long")
    assert transcoded.endswith("/documentaries/long")
    # The two should be in different roots (incoming vs transcoded).
    assert incoming != transcoded


# ─── downloader.* shell-snippet builders ────────────────────────────────────
# These are pure-string functions composed by the command builders. Tests are
# light-touch — we assert structure, not exact byte-equivalence, so the shape
# can evolve.

def test_ssh_to_zikzak_prefix_uses_jump():
    prefix = downloader._ssh_to_zikzak_prefix()
    assert prefix.startswith("ssh")
    assert f"-J {downloader.ZIKZAK_JUMP}" in prefix


def test_ffprobe_has_audio_bash_quotes_var():
    snippet = downloader._ffprobe_has_audio_bash("$_src")
    assert "ffprobe" in snippet
    assert "$_src" in snippet
    assert "select_streams a" in snippet


def test_ffmpeg_transcode_bash_has_both_branches():
    snippet = downloader._ffmpeg_transcode_bash(
        "", "scale=960:540", "-c:v h264_nvenc", "$_src", "$_out", "$_has_audio"
    )
    assert "if [ -z \"$_has_audio\" ]" in snippet
    assert "anullsrc" in snippet  # silent-audio branch
    assert "-map 0:v -map 0:a" in snippet  # has-audio branch
    assert "-movflags +faststart" in snippet


def test_rsync_to_dropbox_bash_targets_zikzak_dropbox():
    snippet = downloader._rsync_to_dropbox_bash('"$_out"')
    assert "mkdir -p" in snippet
    assert downloader.ZIKZAK_DROPBOX in snippet
    assert "rsync" in snippet


def test_build_loki_yt_cmd_shape():
    cmd = downloader._build_loki_yt_cmd(
        "https://youtu.be/foo", "comedy", "short", 42, crop_sides=False
    )
    assert cmd[0] == "ssh"
    # Final element is the script body; spot-check it contains the key stages.
    script = cmd[-1]
    assert "set -e" in script
    assert "https://youtu.be/foo" in script
    assert "42" in script
    assert "rsync" in script
    assert "rm -rf /tmp/intake_42" in script


def test_build_ia_pipeline_cmd_shape():
    cmd = downloader._build_ia_pipeline_cmd(
        99, "Popeye_forPresident", "cartoons", "short", crop_sides=False
    )
    assert cmd[:2] == ["bash", "-c"]
    script = cmd[2]
    assert "Popeye_forPresident" in script
    assert "for _src in" in script
    assert "rsync" in script
    assert "rm -rf /tmp/intake_99" in script


def test_transcode_cmd_parts_nvenc_branch():
    # _transcode_cmd_parts reads HW_ACCEL at module load (from env), so we
    # can't toggle it per-test without reload. Just verify the structure
    # returned matches the current configured accel.
    vf, enc, hw_init = downloader._transcode_cmd_parts(crop_sides=False)
    assert "scale=960:540" in vf
    assert "h264_" in enc
    # crop_sides=True adds the crop filter; check the diff.
    vf_crop, _, _ = downloader._transcode_cmd_parts(crop_sides=True)
    assert "crop=" in vf_crop
    assert "crop=" not in vf


# ─── analyzer pure helpers ──────────────────────────────────────────────────

def test_sanitize_slug_normalizes_case_and_punct():
    assert analyzer._sanitize_slug("Hello World!") == "hello_world"
    assert analyzer._sanitize_slug("foo-bar/baz") == "foo_bar_baz"
    assert analyzer._sanitize_slug("__weird___") == "weird"


def test_sanitize_slug_handles_unicode_by_dropping():
    # Non-ASCII becomes _ then gets coalesced.
    assert analyzer._sanitize_slug("café") == "caf"


def test_fallback_result_shape():
    out = analyzer._fallback_result(123, "because reasons")
    assert set(out) == {
        "category", "is_new_category", "length", "reasoning", "suggested_tags"
    }
    assert out["reasoning"] == "because reasons"
    assert out["suggested_tags"] == []
    assert out["is_new_category"] is False


def test_normalize_classification_passes_known_category_through():
    # Use a category that's definitely in CATEGORIES.
    from config import CATEGORIES
    result = {
        "category": CATEGORIES[0],
        "is_new_category": False,
        "length": "short",
        "suggested_tags": ["foo", "bar"],
    }
    out = analyzer._normalize_classification(result, duration=60)
    assert out["category"] == CATEGORIES[0]
    assert out["is_new_category"] is False
    assert out["length"] == "short"
    assert out["suggested_tags"] == ["foo", "bar"]


def test_normalize_classification_slugifies_new_category():
    result = {
        "category": "New Category Name!",
        "is_new_category": True,
        "length": "medium",
        "suggested_tags": [],
    }
    out = analyzer._normalize_classification(result, duration=600)
    assert out["category"] == "new_category_name"
    assert out["is_new_category"] is True


def test_normalize_classification_recomputes_invalid_length():
    result = {"category": "comedy", "length": "epic", "suggested_tags": []}
    out = analyzer._normalize_classification(result, duration=120)
    # 120s < 300 -> short
    assert out["length"] == "short"


def test_normalize_classification_caps_suggested_tags_at_six():
    result = {
        "category": "comedy",
        "length": "short",
        "suggested_tags": [f"tag{i}" for i in range(10)],
    }
    out = analyzer._normalize_classification(result, duration=60)
    assert len(out["suggested_tags"]) == 6


def test_build_prompt_substitutes_metadata():
    metadata = {
        "title": "Spam And Eggs",
        "duration_seconds": 90,
        "channel": "FoodTV",
        "tags": ["food", "tutorial"],
        "description": "How to make breakfast.",
    }
    prompt = analyzer._build_prompt(metadata, existing_tags=["food", "drink"])
    assert "Spam And Eggs" in prompt
    assert "FoodTV" in prompt
    assert "food, drink" in prompt  # existing tag sample
    assert "How to make breakfast." in prompt


def test_build_prompt_handles_missing_fields_gracefully():
    # When metadata is sparse, defaults kick in but no key errors.
    prompt = analyzer._build_prompt({}, existing_tags=[])
    assert "unknown" in prompt   # channel falls back to "unknown"
    assert "(none yet)" in prompt  # tag sample fallback
