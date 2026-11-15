#!/usr/bin/env bash
#
# Copy a local seeded SQLite database into the box's db volume, where the API reads it. Run
# from the Mac once scripts/deploy.sh has brought the stack up:
#
#   ./scripts/load-data.sh [--force] [--dry-run] [path/to/app.db]
#
#   --help      this text
#   --force     replace a database on the box that already has rows
#   --dry-run   say what would be copied where, and stop
#
#   The database defaults to api/app.db, what `make seed` writes. HOST, STACK_DIR and
#   WAIT_TIMEOUT are deploy.sh's, with its defaults.
#
# In order: snapshot the database with SQLite's backup API (one complete file, WAL pages
# included); refuse if the box's database has any rows, unless --force; copy the snapshot
# to the box; stop the API so nothing writes; restore it into the volume from inside the
# API image, as its uid 10001, so the volume's ownership holds; start the API; check
# /api/health says ok and every table's row count matches the snapshot's.
#
# data/fixtures/runs, replay mode's recordings, is not copied: it is committed, and the API
# image carries data/fixtures, so the deploy ships it.
#
# The box half is box_* functions sent by deploy.sh's on_box(), which this file sources.

# shellcheck source=deploy.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/deploy.sh"
SCRIPT_NAME=load-data

# "table rows" for every table in a database, sorted by name. Run here with the sqlite3 CLI
# and on the box in the API image's Python, so the two lists compare line for line.
table_counts() { # db
  local t
  for t in $(sqlite3 "$1" "select name from sqlite_master where type = 'table' and name not like 'sqlite_%' order by name"); do
    printf '%s %s\n' "$t" "$(sqlite3 "$1" "select count(*) from \"$t\"")"
  done
}

# --- the half that runs on the box ------------------------------------------

# The box database's "table rows" lines, or nothing when there is no database yet. Read in
# a one-off API container: the volume is uid 10001's and the box has no sqlite3.
box_db_counts() { # tag
  box_compose "$1" run --rm --no-deps -T api python -c '
import os, sqlite3
if os.path.exists("/data/app.db"):
    db = sqlite3.connect("/data/app.db")
    query = "select name from sqlite_master where type = ? and name not like ? order by name"
    for (t,) in db.execute(query, ("table", "sqlite_%")):
        print(t, db.execute(f"select count(*) from \"{t}\"").fetchone()[0])
'
}

# A deploy has to have run (the first one leaves an empty database: init_db makes the
# tables). Any row at all is data someone may want, so replacing it takes --force.
box_load_check() { # force
  local tag counts
  tag="$(box_current_tag)"
  [ -n "$tag" ] && [ -f "$STACK_DIR/compose.yaml" ] \
    || die "nothing is deployed in $STACK_DIR yet; run scripts/deploy.sh first. Nothing was changed"
  counts="$(box_db_counts "$tag")" || die "could not read the database on the box. Nothing was changed"
  if printf '%s\n' "$counts" | awk '$2 > 0 { found = 1 } END { exit !found }'; then
    [ "$1" = yes ] || die "the database on the box already has rows:
$counts
Pass --force to replace it. Nothing was changed"
    say "the database on the box has rows; replacing it (--force)"
  else
    say "the database on the box has no rows yet"
  fi
}

# Restore $STACK_DIR/app.db.incoming into the volume with the API stopped, then start it and
# check it serves the same rows.
box_load() { # expected-counts
  local expected="$1" tag got line incoming="$STACK_DIR/app.db.incoming"
  tag="$(box_current_tag)"
  # Read through a bind mount by the container's uid 10001, not the owner of the file.
  chmod 644 "$incoming" || die "could not make $incoming readable"

  step "Stopping the API"
  box_compose "$tag" stop api || { rm -f "$incoming"; die "could not stop the API. Nothing was copied"; }

  step "Restoring into the db volume as the API's user"
  if ! box_compose "$tag" run --rm --no-deps -T -v "$incoming:/seed/app.db:ro" api python -c '
import os, sqlite3
for path in ("/data/app.db.new", "/data/app.db.new-journal"):
    if os.path.exists(path):
        os.remove(path)
src = sqlite3.connect("file:/seed/app.db?immutable=1", uri=True)
new = sqlite3.connect("/data/app.db.new")
src.backup(new)
check = new.execute("pragma integrity_check").fetchone()[0]
new.close()
if check != "ok":
    raise SystemExit("integrity_check: " + check)
for suffix in ("-wal", "-shm"):
    if os.path.exists("/data/app.db" + suffix):
        os.remove("/data/app.db" + suffix)
os.replace("/data/app.db.new", "/data/app.db")
'; then
    rm -f "$incoming"
    box_up "$tag" api || true
    die "the restore failed; the API was started again on the database it had"
  fi
  rm -f "$incoming"

  step "Starting the API"
  box_up "$tag" api && box_health \
    || die "the data is in, but the API did not come back healthy. Look at \`docker compose -f compose.yaml logs api\` in $STACK_DIR"

  # Every table the snapshot has, with its count. The box may have more tables (a newer
  # schema's, made empty by init_db), which is fine.
  got="$(box_db_counts "$tag")" || die "the API is up, but its database could not be read back"
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    printf '%s\n' "$got" | grep -qxF "$line" || die "the box's row counts differ from the snapshot's:
box:
$got
snapshot:
$expected"
  done <<EOF
$expected
EOF
  step "The box's database matches the snapshot"
  printf '%s\n' "$got" | sed 's/^/  /'
}

BOX_FUNCTIONS="$BOX_FUNCTIONS box_db_counts box_load_check box_load"

load_main() {
  set -euo pipefail

  local force='' dry_run='' db="$REPO_ROOT/api/app.db"
  while [ $# -gt 0 ]; do
    case "$1" in
      # Lines 3-13 are the usage block.
      -h | --help) sed -n '3,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; return 0 ;;
      --force) force=yes ;;
      --dry-run) dry_run=yes ;;
      -*) die "unknown option: $1 (see --help)" ;;
      *) db="$1" ;;
    esac
    shift
  done
  [ -f "$db" ] || die "no database at $db; run \`make seed\` first, or name one"

  if [ -n "$dry_run" ]; then
    step "Dry run: nothing copied, nothing sent"
    say "would snapshot  $db  ($(du -h "$db" | cut -f1))"
    say "would copy it to $HOST:$STACK_DIR and restore it into the stack's db volume"
    say "would refuse if the database there has rows${force:+, but --force replaces it}"
    return 0
  fi

  local tmp
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/load-data.XXXXXX")"
  # shellcheck disable=SC2064  # expanded now, on purpose
  trap "rm -rf '$tmp'" EXIT

  step "Snapshotting $db"
  sqlite3 "$db" ".backup \"$tmp/app.db\""
  # One self-contained file; the API turns WAL back on when it connects.
  sqlite3 "$tmp/app.db" 'pragma journal_mode = delete;' >/dev/null
  [ "$(sqlite3 "$tmp/app.db" 'pragma integrity_check;')" = ok ] || die "the snapshot of $db fails integrity_check"
  local counts
  counts="$(table_counts "$tmp/app.db")"
  printf '%s\n' "$counts" | sed 's/^/  /'

  step "Checking $HOST:$STACK_DIR"
  on_box box_load_check "${force:-no}"

  step "Copying the snapshot to $HOST"
  scp -q "$tmp/app.db" "$HOST:$STACK_DIR/app.db.incoming"

  on_box box_load "$counts"
}

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  load_main "$@"
fi
