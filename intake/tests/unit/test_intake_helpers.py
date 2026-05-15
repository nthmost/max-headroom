"""
Tests for the pure helpers in intake.py (the Flask handlers themselves are
exercised via integration tests with a test client, not here).
"""

import flask
import pytest

import intake as intake_mod


# ─── _SLUG_RE + the _valid_* helpers ────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "comedy", "tv_shows", "ch1", "documentaries", "a", "foo123",
])
def test_slug_re_accepts_valid(name):
    assert intake_mod._SLUG_RE.match(name)


@pytest.mark.parametrize("name", [
    "", "1foo",        # must start with a letter
    "foo-bar",         # hyphen not allowed
    "Foo",             # uppercase not allowed
    "foo bar",         # spaces not allowed
    "foo.bar",         # dots not allowed
])
def test_slug_re_rejects_invalid(name):
    assert intake_mod._SLUG_RE.match(name) is None


def test_valid_fname_rejects_path_traversal():
    assert not intake_mod._valid_fname("../etc/passwd")
    assert not intake_mod._valid_fname("/abs/path.mp4")
    assert not intake_mod._valid_fname("a/b.mp4")


def test_valid_fname_accepts_bare_name():
    assert intake_mod._valid_fname("video.mp4")
    assert intake_mod._valid_fname("Indie_Sleaze.mp4")


def test_valid_fname_rejects_empty():
    assert not intake_mod._valid_fname("")
    assert not intake_mod._valid_fname(None)


# ─── _resolved_length ──────────────────────────────────────────────────────

def test_resolved_length_honours_explicit_choice():
    assert intake_mod._resolved_length("short", 9999) == "short"
    assert intake_mod._resolved_length("long", 10) == "long"


def test_resolved_length_classifies_on_auto():
    assert intake_mod._resolved_length("auto", 60) == "short"
    assert intake_mod._resolved_length("auto", 600) == "medium"
    assert intake_mod._resolved_length("auto", 3600) == "long"


def test_resolved_length_defaults_when_auto_and_no_duration():
    # classify_length(None) -> 'medium'
    assert intake_mod._resolved_length("auto", None) == "medium"


# ─── _validate_submit_params (needs a Flask app context for jsonify) ────────

@pytest.fixture
def app_ctx():
    """Flask test app context so jsonify() works in validator tests."""
    app = flask.Flask(__name__)
    with app.app_context():
        yield


def test_validate_submit_params_accepts_valid(app_ctx):
    assert intake_mod._validate_submit_params(
        "youtube", "comedy", "auto", ["https://example.com"]
    ) is None


def test_validate_submit_params_rejects_bad_source(app_ctx):
    err = intake_mod._validate_submit_params("vimeo", "comedy", "auto", ["x"])
    assert err is not None
    response, status = err
    assert status == 400
    assert b"source must be" in response.data


def test_validate_submit_params_rejects_bad_category(app_ctx):
    err = intake_mod._validate_submit_params("youtube", "Has Spaces", "auto", ["x"])
    assert err is not None
    _, status = err
    assert status == 400


def test_validate_submit_params_rejects_bad_length(app_ctx):
    err = intake_mod._validate_submit_params("youtube", "comedy", "epic", ["x"])
    assert err is not None
    _, status = err
    assert status == 400


def test_validate_submit_params_rejects_empty_urls(app_ctx):
    err = intake_mod._validate_submit_params("youtube", "comedy", "auto", [])
    assert err is not None
    _, status = err
    assert status == 400
