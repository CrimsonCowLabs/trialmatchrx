#!/usr/bin/env bash
#
# Tests for scripts/deploy.sh.
#
#   bash scripts/tests/test-deploy.sh
#
# bash 3.2 and what macOS ships; no network, no Docker, no box. Every tool the script
# reaches for - git, ssh, docker, curl - is a stub on a PATH of our own. The ssh stub runs
# what it is sent with `bash -s` right here, so the half of the deploy that runs on the box
# is exercised exactly as shipped, against a temporary directory standing in for
# /app/trialmatchrx.
#
# The docker stub keeps state under $WORK/state - which images are local, which
# "repository tag" pairs the registry holds, which tag is running - and logs every call to
# $WORK/docker-calls, prefixed with the TRIALMATCH_API_IMAGE it was called with.
# flock is a stub too (macOS has none): it fails, as `flock -n` does on a held lock, while
# state/lock-held exists.
# FAKE_UP_FAILS names a tag whose `compose up --wait` fails; FAKE_UNREADY names a tag whose
# /api/health answers `ok: false`; FAKE_UP_LOCKS makes the stack directory read-only once
# compose up has succeeded.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/deploy.sh"

# shellcheck source=/dev/null
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/harness.sh"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/deploy-tests.XXXXXX")"
trap 'chmod -R u+w "$WORK"; rm -rf "$WORK"' EXIT

BIN="$WORK/bin"
mkdir -p "$BIN"

# git: a clean tree at commit 0123456789ab unless FAKE_GIT_STATUS says not.
cat > "$BIN/git" <<STUB
#!/bin/sh
echo "\$*" >> "$WORK/git-calls"
case "\$*" in
  *status*) printf '%s' "\${FAKE_GIT_STATUS:-}" ;;
  *rev-parse*) echo "\${FAKE_COMMIT:-0123456789ab}" ;;
esac
exit 0
STUB

cat > "$BIN/date" <<'STUB'
#!/bin/sh
case "$*" in *%Y%m%d%H%M%S*) echo "${FAKE_NOW:-20261115120000}"; exit 0 ;; esac
exec /bin/date "$@"
STUB

cat > "$BIN/flock" <<STUB
#!/bin/sh
echo "\$*" >> "$WORK/flock-calls"
[ ! -e "$WORK/state/lock-held" ]
STUB

cat > "$BIN/ssh" <<STUB
#!/bin/sh
echo "\$*" >> "$WORK/ssh-calls"
exec bash -s
STUB

cat > "$BIN/docker" <<STUB
#!/bin/bash
S="$WORK/state"
echo "\${TRIALMATCH_API_IMAGE:--} \$*" >> "$WORK/docker-calls"
case "\$*" in
  "buildx build"*)
    for a in "\$@"; do [ "\${prev:-}" = -t ] && img="\$a"; prev="\$a"; done
    repo="\${img%:*}"; echo "\${repo##*/} \${img##*:}" >> "\$S/registry-tags" ;;
  "pull "*) echo "\$2" >> "\$S/local-images" ;;
  "compose -f compose.yaml up"*)
    tag="\${TRIALMATCH_API_IMAGE##*:}"
    if [ -n "\${FAKE_UP_FAILS:-}" ] && [ "\$tag" = "\$FAKE_UP_FAILS" ]; then
      echo "container trialmatchrx-api-1 is unhealthy" >&2; exit 1
    fi
    echo "\$tag" > "\$S/running"
    [ -z "\${FAKE_UP_LOCKS:-}" ] || chmod 500 "$WORK/stack" ;;
  "compose -f compose.yaml down"*) : > "\$S/running" ;;
  "compose -f compose.yaml logs"*) echo "logs for \$*" ;;
  "compose -f compose.yaml ps -q"*) echo "id-\${@: -1}" ;;
  "image ls"*) cat "\$S/local-images" 2>/dev/null ;;
  "rmi "*)
    if [ "\${2##*:}" = "\$(cat "\$S/running" 2>/dev/null)" ]; then
      echo "conflict: image is being used by running container" >&2; exit 1
    fi
    grep -vxF "\$2" "\$S/local-images" > "\$S/li.tmp"; mv "\$S/li.tmp" "\$S/local-images" ;;
  "inspect"*) echo "reg/\${@: -1}:\$(cat "\$S/running" 2>/dev/null)" ;;
esac
exit 0
STUB

# curl: the registry's HTTP API over the state the docker stub keeps, plus the API's
# /api/health. A manifest's digest is sha256:<repo>-<tag> unless state/digest-<repo>-<tag>
# says otherwise; its type is a plain v2 manifest unless state/type-<repo>-<tag> does.
cat > "$BIN/curl" <<STUB
#!/bin/bash
S="$WORK/state"
echo "\$*" >> "$WORK/curl-calls"
url="\${@: -1}"
method=GET; for a in "\$@"; do [ "\${prev:-}" = -X ] && method="\$a"; [ "\$a" = -I ] && method=HEAD; prev="\$a"; done
case "\$method \$url" in
  "GET "*/api/health)
    running="\$(cat "\$S/running" 2>/dev/null)"
    [ -n "\$running" ] || exit 7
    if [ "\$running" = "\${FAKE_UNREADY:-}" ]; then echo '{"ok":false,"demo_mode":"replay"}'
    else echo '{"ok":true,"demo_mode":"off"}'; fi ;;
  "GET "*/v2/) echo '{}' ;;
  "GET "*/v2/_catalog)
    printf '{"repositories":['
    sep=''; for r in \$(cut -d' ' -f1 "\$S/registry-tags" | sort -u); do printf '%s"%s"' "\$sep" "\$r"; sep=,; done
    printf ']}\n' ;;
  "GET "*/tags/list)
    r="\${url%/tags/list}"; r="\${r##*/v2/}"
    printf '{"name":"%s","tags":[' "\$r"
    sep=''; while read -r rr t; do [ "\$rr" = "\$r" ] || continue; printf '%s"%s"' "\$sep" "\$t"; sep=,; done < "\$S/registry-tags"
    printf ']}\n' ;;
  "HEAD "*/manifests/*)
    t="\${url##*/}"; r="\${url%/manifests/*}"; r="\${r##*/v2/}"
    grep -qxF "\$r \$t" "\$S/registry-tags" || { printf 'HTTP/1.1 404 Not Found\r\n\r\n'; exit 0; }
    d="\$(cat "\$S/digest-\$r-\$t" 2>/dev/null || echo "sha256:\$r-\$t")"
    ct="\$(cat "\$S/type-\$r-\$t" 2>/dev/null || echo application/vnd.docker.distribution.manifest.v2+json)"
    printf 'HTTP/1.1 200 OK\r\ncontent-type: %s\r\nDocker-Content-Digest: %s\r\n\r\n' "\$ct" "\$d" ;;
  "DELETE "*/manifests/*)
    echo "\${url##*/}" >> "\$S/deleted-digests"
    printf 'HTTP/1.1 202 Accepted\r\n\r\n' ;;
esac
exit 0
STUB
stub_bin "$BIN" free 'Mem:   3900   1200   800'
stub_bin "$BIN" df 'Filesystem  Size  Used Avail Use% Mounted on'
chmod +x "$BIN"/*

R=reg.example:5000
T=0123456789ab-20261115120000
OLD=aaaaaaaaaaaa-20261101000000

# A fresh box: a stack directory with an .env holding what the API needs and, when given,
# a tag a previous deploy left running (images local, in the registry, in deploys.log).
fresh_box() { # [previous tag]
  chmod -R u+w "$WORK/stack" 2>/dev/null
  rm -rf "$WORK/state" "$WORK/stack" "$WORK"/*-calls
  mkdir -p "$WORK/state" "$WORK/stack"
  : > "$WORK/state/registry-tags"
  : > "$WORK/state/local-images"
  (umask 077; cat > "$WORK/stack/.env" <<EOF
ANTHROPIC_API_KEY=sk-test
MODEL_COMPILE=claude-sonnet-4-5
MODEL_JUDGE=claude-sonnet-4-5
MODEL_PARSE=claude-haiku-4-5
MODEL_CLOSER=claude-sonnet-4-5
DEMO_MODE=off
EOF
  )
  if [ -n "${1:-}" ]; then
    printf 'TRIALMATCH_API_IMAGE=%s\nTRIALMATCH_WEB_IMAGE=%s\n' \
      "$R/trialmatchrx-api:$1" "$R/trialmatchrx-web:$1" >> "$WORK/stack/.env"
    echo "$1" > "$WORK/state/running"
    for repo in trialmatchrx-api trialmatchrx-web; do
      echo "$R/$repo:$1" >> "$WORK/state/local-images"
      echo "$repo $1" >> "$WORK/state/registry-tags"
    done
    echo "2026-11-01T00:00:00Z $1" > "$WORK/stack/deploys.log"
    echo 'compose: the one it was running with' > "$WORK/stack/compose.yaml"
  fi
}

deploy() { # [NAME=value...] [--flag...]
  local settings=()
  while [ $# -gt 0 ] && case "$1" in *=*) true ;; *) false ;; esac; do
    settings+=("$1"); shift
  done
  env PATH="$(sandbox_path "$BIN")" HOST=box REGISTRY="$R" STACK_DIR="$WORK/stack" \
    REGISTRY_URL=http://127.0.0.1:5000 REGISTRY_LOCK="$WORK/gc.lock" ${settings[@]+"${settings[@]}"} bash "$SCRIPT" "$@" 2>&1
}
calls() { cat "$WORK/$1-calls" 2>/dev/null; }
file_mode() { stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1"; }
ups() { calls docker | grep 'compose -f compose.yaml up' | cut -d' ' -f1 | sed 's/.*://' | tr '\n' ' '; }

# --- refusals -------------------------------------------------------------

section 'a dirty tree is refused before anything is built or sent'

fresh_box "$OLD"
out="$(deploy FAKE_GIT_STATUS='?? data/fixtures/runs/')"
assert_status "$?" 1 'exits 1'
assert_contains "$out" 'data/fixtures/runs/' 'names what is uncommitted, untracked files included'
assert_equals "$(calls docker)" '' 'docker was not called'
assert_equals "$(calls ssh)" '' 'the box was not touched'

section 'an uncommitted edit to the scripts is refused too: their box half runs from the working tree'

fresh_box "$OLD"
out="$(deploy FAKE_GIT_STATUS=' M scripts/deploy.sh')"
assert_status "$?" 1 'exits 1'
assert_contains "$out" 'scripts/deploy.sh' 'names the script'
assert_contains "$(calls git | grep status)" ' scripts' 'git status is asked about scripts/'
assert_equals "$(calls docker)$(calls ssh)" '' 'nothing was built or sent'

section 'an .env anyone else on the box could read is refused, naming it, before anything is built'

fresh_box "$OLD"
chmod 644 "$WORK/stack/.env"
out="$(deploy)"
assert_status "$?" 1 'exits 1'
assert_contains "$out" "$WORK/stack/.env on the box is mode 644" 'names the file and its mode'
assert_contains "$out" "chmod 600 $WORK/stack/.env" 'says how to fix it'
assert_equals "$(file_mode "$WORK/stack/.env")" 644 'and does not change it itself'
assert_missing "$(calls docker)" 'buildx' 'nothing was built or pushed'

section 'an .env missing a required value is refused, naming it, before anything is built'

fresh_box
(umask 077; printf 'ANTHROPIC_API_KEY=\nMODEL_COMPILE=claude-sonnet-4-5\nMODEL_JUDGE=claude-sonnet-4-5\n' > "$WORK/stack/.env")
out="$(deploy)"
assert_status "$?" 1 'exits 1'
assert_contains "$out" 'ANTHROPIC_API_KEY' 'names an ANTHROPIC_API_KEY that is there but empty'
assert_contains "$out" 'MODEL_PARSE MODEL_CLOSER' 'names the model ids that are missing'
assert_missing "$out" 'MODEL_COMPILE' 'does not name what is there'
assert_missing "$(calls docker)" 'buildx' 'nothing was built or pushed'
assert_equals "$(cat "$WORK/stack/.env")" "$(printf 'ANTHROPIC_API_KEY=\nMODEL_COMPILE=claude-sonnet-4-5\nMODEL_JUDGE=claude-sonnet-4-5')" \
  'no value was invented'

section 'a first deploy to a box with no stack directory makes it, and refuses for the missing .env'

rm -rf "$WORK/stack" "$WORK"/*-calls
out="$(deploy)"
assert_status "$?" 1 'exits 1'
assert_equals "$(file_mode "$WORK/stack")" 700 'the stack directory exists, mode 700'
assert_contains "$out" 'ANTHROPIC_API_KEY MODEL_COMPILE MODEL_JUDGE MODEL_PARSE MODEL_CLOSER' 'names every required value'
assert_missing "$(calls docker)" 'buildx' 'nothing was built'

section 'KEEP below 2 is refused before anything is built'

fresh_box "$OLD"
out="$(deploy KEEP=1)"
assert_status "$?" 1 'exits 1'
assert_contains "$out" 'KEEP' 'names KEEP'
assert_equals "$(calls docker)$(calls ssh)" '' 'neither docker nor ssh was called'

# --- a deploy that works ----------------------------------------------------

section 'a deploy that comes up healthy replaces both images'

fresh_box "$OLD"
out="$(deploy)"
assert_status "$?" 0 'exits 0'
assert_contains "$(calls docker)" \
  "buildx build --platform linux/amd64 --provenance=false --sbom=false -f $REPO_ROOT/api/Dockerfile -t $R/trialmatchrx-api:$T --push $REPO_ROOT" \
  'builds the api for linux/amd64 and pushes it, tagged commit-time'
assert_contains "$(calls docker)" \
  "-f $REPO_ROOT/web/Dockerfile --build-arg NEXT_PUBLIC_API_URL= -t $R/trialmatchrx-web:$T --push" \
  'builds the web app with a relative API URL and pushes it under the same tag'
assert_contains "$(calls docker)" "pull $R/trialmatchrx-api:$T" 'the box pulls the api'
assert_contains "$(calls docker)" "pull $R/trialmatchrx-web:$T" 'the box pulls the web app'
assert_contains "$(calls docker)" "$R/trialmatchrx-api:$T compose -f compose.yaml up -d --no-build --wait --wait-timeout 150" \
  'compose brings up compose.yaml only, without building, and waits for healthy'
assert_contains "$(calls curl)" 'http://127.0.0.1:8045/api/health' 'then asks /api/health'
assert_contains "$out" '/api/health: {"ok":true' 'and shows what it said'
env_now="$(cat "$WORK/stack/.env")"
assert_contains "$env_now" "TRIALMATCH_API_IMAGE=$R/trialmatchrx-api:$T" '.env names the new api'
assert_contains "$env_now" "TRIALMATCH_WEB_IMAGE=$R/trialmatchrx-web:$T" '.env names the new web app'
assert_equals "$(grep -c '^TRIALMATCH_' "$WORK/stack/.env")" 2 '.env names one image of each'
assert_contains "$env_now" 'ANTHROPIC_API_KEY=sk-test' '.env keeps its other lines'
assert_equals "$(file_mode "$WORK/stack/.env")" 600 '.env is still mode 600'
assert_equals "$(tail -1 "$WORK/stack/deploys.log" | cut -d' ' -f2)" "$T" 'the tag is appended to deploys.log'
assert_equals "$(cat "$WORK/stack/compose.yaml")" "$(cat "$REPO_ROOT/compose.yaml")" "the repo's compose.yaml is on the box"
assert_equals "$(ls "$WORK/stack")" "$(printf 'compose.yaml\ndeploys.log')" \
  'and nothing else is shipped: no override, no .next or .previous left behind'
assert_contains "$out" "api: reg/id-api:$T" 'ends by saying what the api container runs'
assert_contains "$out" 'Mem:' 'and what the box has left'

section 'the API port in the box .env is the one /api/health is asked on'

fresh_box "$OLD"
echo 'TRIALMATCH_API_PORT=18045' >> "$WORK/stack/.env"
out="$(deploy)"
assert_status "$?" 0 'exits 0'
assert_contains "$(calls curl)" 'http://127.0.0.1:18045/api/health' 'asks on 18045'

section 'a tag that is already running is refused, not redeployed over itself'

fresh_box "$T"
env_before="$(cat "$WORK/stack/.env")"
out="$(deploy)"
assert_status "$?" 1 'exits 1'
assert_contains "$out" "$T is already what .env names" 'says why'
assert_equals "$(ups)" '' 'compose is not asked to bring anything up'
assert_equals "$(cat "$WORK/stack/.env")" "$env_before" '.env is unchanged'

section 'an .env that cannot be rewritten after a healthy up says what to set by hand'

fresh_box "$OLD"
out="$(deploy FAKE_UP_LOCKS=1)"
assert_status "$?" 1 'exits 1'
assert_contains "$out" "$T is running, but $WORK/stack/.env still names $OLD" 'says what runs and what .env names'
assert_contains "$out" "TRIALMATCH_WEB_IMAGE=$R/trialmatchrx-web:$T" 'gives the lines to set'

# --- a deploy that fails ----------------------------------------------------

section 'new containers that never become healthy: the previous images are put back'

fresh_box "$OLD"
env_before="$(cat "$WORK/stack/.env")"
out="$(deploy FAKE_UP_FAILS="$T")"
assert_status "$?" 1 'exits 1'
assert_contains "$out" 'logs for compose -f compose.yaml logs --no-color --tail 50 api web' "shows api's and web's logs"
assert_equals "$(ups)" "$T $OLD " 'compose was asked for the new tag, then the previous one'
assert_equals "$(cat "$WORK/state/running")" "$OLD" 'the previous images are running'
assert_contains "$out" "$T failed and was rolled back: $OLD is running again" 'and it says so'
assert_equals "$(cat "$WORK/stack/.env")" "$env_before" '.env is exactly as it was'
assert_equals "$(file_mode "$WORK/stack/.env")" 600 '.env is still mode 600'
assert_equals "$(cat "$WORK/stack/compose.yaml")" 'compose: the one it was running with' 'the previous compose.yaml is back'
assert_equals "$(wc -l < "$WORK/stack/deploys.log" | tr -d ' ')" 1 'nothing is added to deploys.log'
assert_missing "$(calls docker)" 'rmi' 'nothing is pruned on the box'
assert_missing "$(calls curl)" 'DELETE' 'nothing is deleted from the registry'

section 'healthy containers whose /api/health says ok: false are rolled back too'

fresh_box "$OLD"
out="$(deploy FAKE_UNREADY="$T")"
assert_status "$?" 1 'exits 1'
assert_contains "$out" '/api/health does not say ok: true' 'says why'
assert_equals "$(ups)" "$T $OLD " 'the previous tag is brought back up'
assert_contains "$(cat "$WORK/stack/.env")" "TRIALMATCH_API_IMAGE=$R/trialmatchrx-api:$OLD" '.env still names the previous images'

section 'a first deploy that fails says so, stops what it started, and changes no .env'

fresh_box
out="$(deploy FAKE_UP_FAILS="$T")"
assert_status "$?" 1 'exits 1'
assert_equals "$(ups)" "$T " 'compose up was tried once, with no rollback'
assert_contains "$(calls docker)" 'compose -f compose.yaml down' 'the new containers are stopped'
assert_contains "$out" 'no earlier image to put back' 'says there was nothing to put back'
assert_missing "$(cat "$WORK/stack/.env")" 'TRIALMATCH_' '.env names no image'

# --- the prune --------------------------------------------------------------

section 'after a deploy that works, the box and registry keep the newest KEEP tags and no more'

# Deployed 1111, 2222, 3333, 4444 in that order (not name order); 9999 was pushed by a deploy
# that never ran. 2222's api shares 3333's manifest, and 9999's web shares 1111's (one DELETE
# takes both). KeyIDPro's tags are not ours to delete.
fresh_box
for t in 4444aaaaaaaa 1111aaaaaaaa 3333aaaaaaaa 2222aaaaaaaa 9999aaaaaaaa; do
  for repo in trialmatchrx-api trialmatchrx-web; do
    echo "$repo $t" >> "$WORK/state/registry-tags"
    echo "$R/$repo:$t" >> "$WORK/state/local-images"
  done
done
echo 'keyidpro-api 50750369b312' >> "$WORK/state/registry-tags"
echo 'sha256:trialmatchrx-api-3333aaaaaaaa' > "$WORK/state/digest-trialmatchrx-api-2222aaaaaaaa"
echo 'sha256:trialmatchrx-web-1111aaaaaaaa' > "$WORK/state/digest-trialmatchrx-web-9999aaaaaaaa"
echo 'someone/else:latest' >> "$WORK/state/local-images"
: > "$WORK/stack/deploys.log"
day=1
for t in 1111aaaaaaaa 2222aaaaaaaa 3333aaaaaaaa 4444aaaaaaaa; do
  echo "2026-11-0${day}T00:00:00Z $t" >> "$WORK/stack/deploys.log"; day=$((day + 1))
done
printf 'TRIALMATCH_API_IMAGE=%s\nTRIALMATCH_WEB_IMAGE=%s\n' \
  "$R/trialmatchrx-api:4444aaaaaaaa" "$R/trialmatchrx-web:4444aaaaaaaa" >> "$WORK/stack/.env"
echo 4444aaaaaaaa > "$WORK/state/running"

out="$(deploy KEEP=3)"
assert_status "$?" 0 'exits 0'
deleted="$(sort "$WORK/state/deleted-digests" 2>/dev/null | tr '\n' ' ')"
assert_equals "$deleted" 'sha256:trialmatchrx-api-1111aaaaaaaa sha256:trialmatchrx-api-9999aaaaaaaa sha256:trialmatchrx-web-1111aaaaaaaa sha256:trialmatchrx-web-2222aaaaaaaa ' \
  'the registry loses the oldest deploys and the one that never ran, in both repositories, each manifest once, and nothing of KeyIDPro'
assert_contains "$out" 'deleting trialmatchrx-web:9999aaaaaaaa' 'a tag going with a manifest already deleted is still named'
assert_missing "$out" 'WARN' 'and nothing warns'
assert_contains "$out" 'left trialmatchrx-api:2222aaaaaaaa: it shares its manifest' 'a tag sharing a kept manifest is left'
assert_contains "$(calls docker)" 'exec registry registry garbage-collect --delete-untagged /etc/docker/registry/config.yml' \
  'the registry collects its garbage'
assert_contains "$(calls docker)" 'restart registry' 'then is restarted'
assert_equals "$(calls flock)" '-n 9' 'all under flock -n on the registry lock'
left="$(sort "$WORK/state/local-images" | tr '\n' ' ')"
assert_equals "$left" "$R/trialmatchrx-api:$T $R/trialmatchrx-api:4444aaaaaaaa $R/trialmatchrx-web:$T $R/trialmatchrx-web:4444aaaaaaaa someone/else:latest " \
  'the box keeps the current and previous images, and what is not ours'

section 'an index anywhere in the shared registry stops the registry prune'

fresh_box "$OLD"
echo 'keyidpro-api 50750369b312' >> "$WORK/state/registry-tags"
echo 'application/vnd.oci.image.index.v1+json' > "$WORK/state/type-keyidpro-api-50750369b312"
echo "trialmatchrx-api 1111aaaaaaaa" >> "$WORK/state/registry-tags"
out="$(deploy)"
assert_status "$?" 0 'exits 0, the deploy itself having worked'
assert_contains "$out" 'keyidpro-api:50750369b312 is an index' 'says which tag is an index'
assert_missing "$(calls curl)" 'DELETE' 'deletes nothing from the registry'
assert_missing "$(calls docker)" 'garbage-collect' 'does not garbage-collect'

section 'a registry lock held elsewhere skips the registry prune, and the deploy still succeeds'

fresh_box "$OLD"
echo "trialmatchrx-api 1111aaaaaaaa" >> "$WORK/state/registry-tags"
touch "$WORK/state/lock-held"
out="$(deploy)"
assert_status "$?" 0 'exits 0'
assert_contains "$out" "SKIP  $WORK/gc.lock is held by another prune" 'says the prune was skipped, and why'
assert_missing "$out" 'the prune did not finish' 'which is not reported as a failed prune'
assert_missing "$(calls curl)" 'DELETE' 'deletes nothing from the registry'
assert_missing "$(calls docker)" 'garbage-collect' 'does not garbage-collect'
assert_missing "$(calls docker)" 'restart registry' 'does not restart the registry'
assert_contains "$(cat "$WORK/stack/.env")" "TRIALMATCH_API_IMAGE=$R/trialmatchrx-api:$T" 'the new images are still recorded'

# --- --help and --dry-run ---------------------------------------------------

section '--help and --dry-run touch nothing'

fresh_box "$OLD"
out="$(deploy --help)"
assert_status "$?" 0 '--help exits 0'
assert_contains "$out" 'WAIT_TIMEOUT' '--help lists the settings'
assert_missing "$out" 'set -e' '--help stops at the usage block'
out="$(deploy --dry-run)"
assert_status "$?" 0 '--dry-run exits 0'
assert_contains "$out" "$R/trialmatchrx-api:$T" '--dry-run names the api image'
assert_contains "$out" "$R/trialmatchrx-web:$T" '--dry-run names the web image'
assert_contains "$out" "push both to $R" '--dry-run names the registry'
assert_contains "$out" "on box in $WORK/stack" '--dry-run names the host and stack dir'
assert_equals "$(calls docker)$(calls ssh)" '' '--dry-run calls neither docker nor ssh'

finish_up
