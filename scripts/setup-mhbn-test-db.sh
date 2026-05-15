#!/bin/bash
# setup-mhbn-test-db.sh
#
# Creates / refreshes the mhbn_test database on loki by cloning mhbn's
# schema. Used as the target for intake/ integration tests and as the DB
# the headroom test-pair pipeline writes through.
#
# Run on loki (as a user with sudo + postgres access):
#   ./scripts/setup-mhbn-test-db.sh
#
# Re-running is safe — schema is dropped and recreated; existing data in
# mhbn_test is destroyed. mhbn itself is never touched.

set -euo pipefail

DB_PROD="${DB_PROD:-mhbn}"
DB_TEST="${DB_TEST:-mhbn_test}"
DB_USER="${DB_USER:-mhbn}"

echo "==> Ensuring $DB_TEST exists, owned by $DB_USER"
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_TEST'" | grep -q 1; then
    sudo -u postgres createdb -O "$DB_USER" "$DB_TEST"
fi

echo "==> Wiping any existing schema in $DB_TEST"
sudo -u postgres psql -d "$DB_TEST" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
sudo -u postgres psql -d "$DB_TEST" -c "GRANT ALL ON SCHEMA public TO $DB_USER;"

echo "==> Cloning schema from $DB_PROD into $DB_TEST"
sudo -u postgres pg_dump --schema-only --no-owner --no-privileges "$DB_PROD" \
    | sudo -u postgres psql -d "$DB_TEST" > /dev/null

echo "==> Granting access on cloned objects to $DB_USER"
sudo -u postgres psql -d "$DB_TEST" <<EOF
GRANT ALL ON ALL TABLES    IN SCHEMA public TO $DB_USER;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO $DB_USER;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO $DB_USER;
EOF

echo "==> Done. Connect with:"
echo "    psql -h 127.0.0.1 -U $DB_USER -d $DB_TEST"
echo "    (or via the zikzak->loki tunnel: -h 127.0.0.1 -p 5435)"
