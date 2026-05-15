"""
Integration-test fixtures. All tests in this directory hit a real postgres
database — they require MHBN_TEST_DATABASE_URL pointing at a populated
mhbn_test schema (see tests/README.md for setup).
"""

import os

import pytest


def _test_database_url():
    """Return the test DB URL or None if not configured."""
    return os.environ.get("MHBN_TEST_DATABASE_URL", "")


@pytest.fixture(scope="session", autouse=True)
def _require_test_db():
    """Skip the entire integration suite if no test DB is configured."""
    url = _test_database_url()
    if not url:
        pytest.skip(
            "MHBN_TEST_DATABASE_URL not set — skipping integration tests. "
            "See tests/README.md for setup.",
            allow_module_level=True,
        )


@pytest.fixture(scope="session")
def db_module():
    """
    Import the `db` module with DATABASE_URL pointed at the test DB.

    db.py reads DATABASE_URL at module-import time, so we set it in the env
    before the first import and patch the module global as a belt-and-braces
    measure in case it's been imported transitively already.
    """
    os.environ["DATABASE_URL"] = _test_database_url()
    import db  # noqa: E402
    db.DATABASE_URL = _test_database_url()
    return db


@pytest.fixture
def clean_jobs(db_module):
    """
    Wipe test-marked rows from the jobs table before and after each test.

    Tests should use category='zzz_test' or url prefix 'test://' so cleanup
    is safe and idempotent.
    """
    def _purge():
        with db_module.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM jobs WHERE category = 'zzz_test' "
                    "OR url LIKE 'test://%'"
                )
    _purge()
    yield
    _purge()


@pytest.fixture
def clean_test_categories(db_module):
    """Remove user/tag categories created by tests."""
    def _purge():
        with db_module.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM categories WHERE name LIKE 'zzz_test%' "
                    "AND is_builtin = FALSE"
                )
    _purge()
    yield
    _purge()
