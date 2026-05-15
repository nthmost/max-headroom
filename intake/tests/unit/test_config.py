"""Tests for the small pure helpers in config.py."""

import config


def test_classify_length_short():
    assert config.classify_length(60) == "short"
    assert config.classify_length(299) == "short"


def test_classify_length_medium():
    assert config.classify_length(300) == "medium"
    assert config.classify_length(1799) == "medium"


def test_classify_length_long():
    assert config.classify_length(1800) == "long"
    assert config.classify_length(7200) == "long"


def test_classify_length_defaults_medium_when_none():
    # Callers pass None when metadata lookup fails; we deliberately fall back
    # to 'medium' as the "safe middle" rather than raising or returning unknown.
    assert config.classify_length(None) == "medium"


def test_classify_length_defaults_medium_when_zero():
    # Zero duration shows up when ffprobe can't read the file (e.g. live stream).
    assert config.classify_length(0) == "medium"
