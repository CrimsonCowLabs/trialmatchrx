#!/usr/bin/env bash
#
# Tests for scripts/load-data.sh.
#
#   bash scripts/tests/test-load-data.sh
#
# Same rules as test-deploy.sh: bash 3.2 and what macOS ships (sqlite3 included), no
# network, no Docker, no box. git reports a clean tree unless FAKE_GIT_STATUS says not. ssh runs the box half here; scp copies; the docker stub stands
# in for the API container: its `run ... python -c` reads or replaces $WORK/volume/app.db
# with the real sqlite3, so the counts compared are a real database's. It logs every call to
# $WORK/docker-calls. FAKE_RESTORE_FAILS makes the restore fail.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/load-data.sh"

# shellcheck source=/dev/null
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/harness.sh"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/load-data-tests.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

BIN="$WORK/bin"
mkdir -p "$BIN"

cat > "$BIN/git" <<STUB
#!/bin/sh
echo "\$*" >> "$WORK/git-calls"
case "\$*" in *status*) printf '%s' "\${FAKE_GIT_STATUS:-}" ;; esac
exit 0
STUB

cat > "$BIN/ssh" <<STUB
#!/bin/sh
echo "\$*" >> "$WORK/ssh-calls"
exec bash -s
STUB

cat > "$BIN/scp" <<STUB
#!/bin/sh
echo "\$*" >> "$WORK/scp-calls"
for a in "\$@"; do src="\${dst:-}"; dst="\$a"; done
exec cp "\$src" "\${dst#*:}"
STUB

cat > "$BIN/docker" <<STUB
#!/bin/bash
S="$WORK/state"
V="$WORK/volume"
echo "\$*" | head -1 >> "$WORK/docker-calls"
case "\$*" in
  "compose -f compose.yaml stop api"*) : > "\$S/running" ;;
  "compose -f compose.yaml up"*) echo up > "\$S/running" ;;
  "compose -f compose.yaml run --rm --no-deps -T -v "*)
    [ -z "\${FAKE_RESTORE_FAILS:-}" ] || { echo 'integrity_check: malformed' >&2; exit 1; }
    [ -z "\$(cat "\$S/running")" ] || { echo 'restored while the API was running' >&2; exit 1; }
    mount="\${9%%:/seed/*}"
    perms="\$(stat -f %Lp "\$mount" 2>/dev/null || stat -c %a "\$mount")"
    echo "\$perms" > "\$S/incoming-mode"
    cp "\$mount" "\$V/app.db" ;;
  "compose -f compose.yaml run --rm --no-deps -T api"*)
    [ -f "\$V/app.db" ] || exit 0
    for t in \$(sqlite3 "\$V/app.db" "select name from sqlite_master where type = 'table' and name not like 'sqlite_%' order by name"); do
      printf '%s %s\n' "\$t" "\$(sqlite3 "\$V/app.db" "select count(*) from \"\$t\"")"
    done ;;
esac
exit 0
STUB

cat > "$BIN/curl" <<STUB
#!/bin/bash
[ -n "\$(cat "$WORK/state/running")" ] || exit 7
echo '{"ok":true,"demo_mode":"off"}'
STUB
chmod +x "$BIN"/*

# A seeded database: some trials, some patients, a table with nothing in it.
make_db() { # path trials patients
  rm -f "$1"
  sqlite3 "$1" "create table trials_cache (nct_id text primary key);
    create table cohort (id integer primary key); create table runs (id text);"
  local i=0
  while [ "$i" -lt "$2" ]; do sqlite3 "$1" "insert into trials_cache values ('NCT$i')"; i=$((i + 1)); done
  i=0
  while [ "$i" -lt "$3" ]; do sqlite3 "$1" "insert into cohort default values"; i=$((i + 1)); done
}

R=reg.example:5000
# A deployed box: compose.yaml, an .env naming a tag, the API running, and a volume holding
# what the first start leaves (empty tables) unless told otherwise.
fresh_box() {
  rm -rf "$WORK/state" "$WORK/stack" "$WORK/volume" "$WORK"/*-calls
  mkdir -p "$WORK/state" "$WORK/stack" "$WORK/volume"
  echo up > "$WORK/state/running"
  echo 'services: {}' > "$WORK/stack/compose.yaml"
  (umask 077; printf 'ANTHROPIC_API_KEY=sk-test\nTRIALMATCH_API_IMAGE=%s\nTRIALMATCH_WEB_IMAGE=%s\n' \
    "$R/trialmatchrx-api:aaaa-1" "$R/trialmatchrx-web:aaaa-1" > "$WORK/stack/.env")
  make_db "$WORK/volume/app.db" 0 0
}

make_db "$WORK/seeded.db" 3 5

load() { # [NAME=value...] [args...]
  local settings=()
  while [ $# -gt 0 ] && case "$1" in *=*) true ;; *) false ;; esac; do
    settings+=("$1"); shift
  done
  env PATH="$(sandbox_path "$BIN")" HOST=box REGISTRY="$R" STACK_DIR="$WORK/stack" \
    ${settings[@]+"${settings[@]}"} bash "$SCRIPT" "$@" 2>&1
}
calls() { cat "$WORK/$1-calls" 2>/dev/null; }
volume_counts() { sqlite3 "$WORK/volume/app.db" 'select count(*) from trials_cache; select count(*) from cohort;' | tr '\n' ' '; }

section 'a load into a freshly deployed box copies the database in, as the API user, with the API stopped'

fresh_box
out="$(load "$WORK/seeded.db")"
assert_status "$?" 0 'exits 0'
assert_equals "$(volume_counts)" '3 5 ' 'the volume holds the seeded trials and cohort'
assert_equals "$(calls docker | grep -c 'stop api')" 1 'the API is stopped once'
stop_at="$(calls docker | grep -n 'stop api' | cut -d: -f1)"
restore_at="$(calls docker | grep -n ':/seed/app.db:ro api' | cut -d: -f1)"
up_at="$(calls docker | grep -n ' up -d --no-build --wait' | cut -d: -f1)"
if [ -n "$stop_at" ] && [ -n "$restore_at" ] && [ -n "$up_at" ] && [ "$stop_at" -lt "$restore_at" ] && [ "$restore_at" -lt "$up_at" ]; then
  ok 'stop, then restore, then start'
else
  bad 'stop, then restore, then start' "stop $stop_at, restore $restore_at, up $up_at"
fi
assert_contains "$(calls docker)" "-v $WORK/stack/app.db.incoming:/seed/app.db:ro api python -c" \
  'the restore runs in the API image (its user, uid 10001), the snapshot mounted read-only'
assert_equals "$(cat "$WORK/state/incoming-mode")" 644 'the snapshot is readable by that user'
assert_contains "$(calls scp)" "$WORK/stack/app.db.incoming" 'the snapshot is copied beside the stack'
assert_equals "$(ls "$WORK/stack")" 'compose.yaml' 'and removed once restored'
assert_contains "$out" '/api/health: {"ok":true' 'the API is checked healthy afterwards'
assert_contains "$out" "The box's database matches the snapshot" 'and its row counts match'
assert_contains "$out" 'trials_cache 3' 'which it prints'

section 'a database with rows on the box is refused without --force, and kept'

fresh_box
make_db "$WORK/volume/app.db" 7 2
out="$(load "$WORK/seeded.db")"
assert_status "$?" 1 'exits 1'
assert_contains "$out" 'already has rows' 'says why'
assert_contains "$out" 'trials_cache 7' 'shows what is there'
assert_contains "$out" '--force' 'says how to replace it'
assert_equals "$(volume_counts)" '7 2 ' 'the database on the box is untouched'
assert_missing "$(calls docker)" 'stop api' 'the API is not stopped'
assert_equals "$(calls scp)" '' 'nothing is copied'

section '--force replaces it'

out="$(load "$WORK/seeded.db" --force)"
assert_status "$?" 0 'exits 0'
assert_equals "$(volume_counts)" '3 5 ' 'the volume holds the seeded database'

section 'a box with nothing deployed is refused'

fresh_box
rm "$WORK/stack/compose.yaml"
out="$(load "$WORK/seeded.db")"
assert_status "$?" 1 'exits 1'
assert_contains "$out" 'run scripts/deploy.sh first' 'says to deploy first'
assert_equals "$(calls scp)" '' 'nothing is copied'

section 'a restore that fails starts the API again on what it had'

fresh_box
out="$(load FAKE_RESTORE_FAILS=1 "$WORK/seeded.db")"
assert_status "$?" 1 'exits 1'
assert_contains "$out" 'the restore failed' 'says so'
assert_equals "$(cat "$WORK/state/running")" up 'the API is running again'
assert_equals "$(volume_counts)" '0 0 ' 'on the database it had'
assert_equals "$(ls "$WORK/stack")" 'compose.yaml' 'the snapshot is not left behind'

section 'an uncommitted edit to the scripts is refused before anything is read or sent'

fresh_box
out="$(load FAKE_GIT_STATUS=' M scripts/load-data.sh' "$WORK/seeded.db")"
assert_status "$?" 1 'exits 1'
assert_contains "$out" 'scripts/load-data.sh' 'names the script'
assert_contains "$(calls git | grep status)" '-- scripts' 'git status is asked about scripts/ only'
assert_equals "$(calls docker)$(calls ssh)$(calls scp)" '' 'neither docker, ssh nor scp was called'
assert_missing "$out" 'Snapshotting' 'the database is not even snapshotted'

section 'a missing local database, --help and --dry-run touch nothing'

fresh_box
out="$(load "$WORK/nope.db")"
assert_status "$?" 1 'a missing database exits 1'
assert_contains "$out" 'make seed' 'and says how to make one'
out="$(load --help)"
assert_status "$?" 0 '--help exits 0'
assert_contains "$out" '--force' '--help lists --force'
assert_missing "$out" 'shellcheck' '--help stops at the usage block'
out="$(load --dry-run "$WORK/seeded.db")"
assert_status "$?" 0 '--dry-run exits 0'
assert_contains "$out" "$WORK/seeded.db" '--dry-run names the database'
assert_contains "$out" "box:$WORK/stack" '--dry-run names the host and stack dir'
assert_equals "$(calls docker)$(calls ssh)$(calls scp)" '' '--dry-run calls neither docker, ssh nor scp'

finish_up
