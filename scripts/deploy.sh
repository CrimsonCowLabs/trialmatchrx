#!/usr/bin/env bash
#
# Build TrialMatch Rx's two images (api, web) for ccl-vps, push them to the box's registry,
# and bring them up there. One command, run from the Mac, from anywhere in the repo:
#
#   ./scripts/deploy.sh
#
#   --help          this text
#   --dry-run       say what would be built and where it would go, and stop
#
#   HOST=aaron@ccl-vps                       where to ssh
#   REGISTRY=ccl-vps.tailc2e228.ts.net:5000  where to push, and where the box pulls
#   REGISTRY_URL=http://127.0.0.1:5000       the registry's API, from the box
#   REGISTRY_CONTAINER=registry              the registry's container on the box
#   REGISTRY_LOCK=/app/registry/.gc.lock     flock held on the box while the registry is pruned
#   STACK_DIR=/app/trialmatchrx              the stack on the box: .env, compose.yaml
#   KEEP=3                                   tags the registry keeps, at least 2
#   WAIT_TIMEOUT=150                         seconds `compose up --wait` may take
#
# Both images are tagged <commit>-<UTC yyyymmddHHMMSS>. In order: refuse a dirty tree;
# check the box's .env has the secrets the API needs; build both for linux/amd64 and push;
# bring them up on the box and check /api/health says ok; prune; say what is running. A
# failed deploy leaves the previous images running and .env naming them. The data is
# scripts/load-data.sh's; README.md ("Deploying to ccl-vps") has the first-time steps.
#
# This is KeyIDPro's scripts/deploy.sh, cut down to this app: two images under one tag, no
# migrate step, no --allow-dirty. The box is reached only through on_box(), which sends the
# box_* functions down `ssh host 'bash -s'`, so the half that runs there lives in this file
# and scripts/tests/test-deploy.sh runs it as shipped. load-data.sh sources this file for
# on_box and the helpers it shares.
#
# New images are tried with TRIALMATCH_API_IMAGE / TRIALMATCH_WEB_IMAGE set in the shell,
# which compose prefers to .env, and .env is changed only once they are up, healthy, and
# /api/health answers `ok: true` (the container healthcheck is liveness only: any 200
# passes). Only compose.yaml is shipped, and compose runs with `-f compose.yaml`, so the
# local compose.override.yaml (a second Caddy) can never load on the box.
#
# Old images go only after a deploy that worked: on the box, every image of ours but the
# current and previous; in the registry, every tag but the newest KEEP by deploys.log. The
# registry is shared with KeyIDPro, so its delete + garbage-collect runs under `flock -n` on
# REGISTRY_LOCK, and a deploy that finds the lock held skips that prune. KeyIDPro's deploy
# does not take the lock yet, so until it does the guard only stops two of these at once.
#
# `set -e` lives inside main() so that the tests and load-data.sh can source this file.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

: "${HOST:=aaron@ccl-vps}"
: "${REGISTRY:=ccl-vps.tailc2e228.ts.net:5000}"
: "${REGISTRY_URL:=http://127.0.0.1:5000}"
: "${REGISTRY_CONTAINER:=registry}"
# Beside the registry's own compose.yaml, where either app's deploy can reach it.
: "${REGISTRY_LOCK:=/app/registry/.gc.lock}"
: "${STACK_DIR:=/app/trialmatchrx}"
: "${KEEP:=3}"
# Five of the healthchecks' 30-second intervals: start, the first check, room for retries.
: "${WAIT_TIMEOUT:=150}"

readonly REPOSITORIES='trialmatchrx-api trialmatchrx-web'
# What the API refuses to run the live pipeline without. config.py defaults the model ids,
# but the box states them so a code change to the defaults can't swap a model in prod.
readonly REQUIRED_ENV='ANTHROPIC_API_KEY MODEL_COMPILE MODEL_JUDGE MODEL_PARSE MODEL_CLOSER'
# Manifest media types: one image, and an index of several (see box_prune_registry).
readonly IMAGE_TYPES='application/vnd.docker.distribution.manifest.v2+json application/vnd.oci.image.manifest.v1+json'
readonly INDEX_TYPES='application/vnd.oci.image.index.v1+json application/vnd.docker.distribution.manifest.list.v2+json'

say()  { printf '  %s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
die()  { printf '\n%s: %s\n' "${SCRIPT_NAME:-deploy}" "$*" >&2; exit 1; }

# Changes, tracked or untracked (not ignored), in what goes into an image or onto the box.
# Untracked counts: the build context is the working tree, so an unrecorded
# data/fixtures/runs would ship under a tag that names a commit without it. scripts/ counts
# because the box half of this file and load-data.sh runs from the working tree too.
# load-data.sh, which builds nothing, passes just scripts.
uncommitted() { # [pathspec...]
  [ $# -gt 0 ] || set -- api web data/fixtures compose.yaml .dockerignore scripts
  git -C "$REPO_ROOT" status --porcelain -- "$@"
}

# One of our images, by repository and tag.
image_ref() { # repository tag
  printf '%s/%s:%s\n' "$REGISTRY" "$1" "$2"
}

# --- the half that runs on the box ------------------------------------------
#
# Everything from here to on_box() runs on the box. Each function reads only the settings
# on_box passes and says what went wrong itself, since its stderr is what comes back.

# One variable's value from the stack's .env, or nothing.
box_env_value() { # name
  [ -f "$STACK_DIR/.env" ] || return 0
  sed -n "s/^$1=//p" "$STACK_DIR/.env" | tail -1
}

# The tag .env's images carry: what is running, and what a failed deploy goes back to.
box_current_tag() {
  local image
  image="$(box_env_value TRIALMATCH_API_IMAGE)"
  [ -z "$image" ] || printf '%s\n' "${image##*:}"
}

# The stack directory is made here (mode 700, like /app/keyidpro); its .env never is, and
# one anyone else on the box could read is refused rather than fixed behind the user's back.
box_preflight() {
  local name missing='' mode
  mkdir -p "$STACK_DIR" && chmod 700 "$STACK_DIR" || die "could not make $STACK_DIR"
  if [ -f "$STACK_DIR/.env" ]; then
    # GNU stat on the box; BSD stat where the tests run.
    mode="$(stat -c %a "$STACK_DIR/.env" 2>/dev/null || stat -f %Lp "$STACK_DIR/.env")"
    [ "$mode" = 600 ] || die "$STACK_DIR/.env on the box is mode $mode; it holds the API key, so it has to be 600.
Run: chmod 600 $STACK_DIR/.env. Nothing was built."
  fi
  for name in $REQUIRED_ENV; do
    [ -n "$(box_env_value "$name")" ] || missing="$missing $name"
  done
  [ -z "$missing" ] || die "$STACK_DIR/.env on the box has no value for:$missing
Add them by hand (mode 600); README.md \"Deploying to ccl-vps\" says how. Nothing was built."
  say "$STACK_DIR/.env has what the API needs"
}

# The repo's compose.yaml, as an argument because stdin is the script. Put beside the live
# one, which stays until box_release knows the new images are healthy.
box_stage_compose() { # contents
  printf '%s\n' "$1" > "$STACK_DIR/compose.yaml.next"
}

# Point .env's two image lines at a tag, keeping every other line, mode 600 throughout.
box_set_tag() { # tag
  local tmp
  tmp="$(umask 077 && mktemp "$STACK_DIR/.env.XXXXXX")" \
    || { say "could not make a temporary file in $STACK_DIR"; return 1; }
  if ! {
    grep -v -e '^TRIALMATCH_API_IMAGE=' -e '^TRIALMATCH_WEB_IMAGE=' "$STACK_DIR/.env" || true
    printf 'TRIALMATCH_API_IMAGE=%s\n' "$(image_ref trialmatchrx-api "$1")"
    printf 'TRIALMATCH_WEB_IMAGE=%s\n' "$(image_ref trialmatchrx-web "$1")"
  } > "$tmp"; then
    rm -f "$tmp"; say "could not write $tmp"; return 1
  fi
  mv "$tmp" "$STACK_DIR/.env" || { rm -f "$tmp"; say "could not move $tmp over $STACK_DIR/.env"; return 1; }
}

# Compose against the stack's compose.yaml only, with both images of a tag named in the
# shell, which beats .env when compose fills in ${TRIALMATCH_*_IMAGE}.
box_compose() { # tag compose-args...
  local tag="$1"; shift
  (cd "$STACK_DIR" \
    && TRIALMATCH_API_IMAGE="$(image_ref trialmatchrx-api "$tag")" \
       TRIALMATCH_WEB_IMAGE="$(image_ref trialmatchrx-web "$tag")" \
       docker compose -f compose.yaml "$@")
}

box_up() { # tag [service...]
  local tag="$1"; shift
  box_compose "$tag" up -d --no-build --wait --wait-timeout "$WAIT_TIMEOUT" "$@"
}

# Demo readiness, not just liveness: `ok: false` (replay mode with no recorded runs) is a
# running API that can't serve the demo, which the container healthcheck lets through.
box_health() {
  local port body
  port="$(box_env_value TRIALMATCH_API_PORT)"
  body="$(curl -fsS --max-time 10 "http://127.0.0.1:${port:-8045}/api/health")" \
    || { say "no answer from 127.0.0.1:${port:-8045}/api/health"; return 1; }
  say "/api/health: $body"
  case "$body" in *'"ok":true'*) return 0 ;; esac
  say "/api/health does not say ok: true"
  return 1
}

# Give up on a release before anything is brought up: drop the staged compose.yaml and fail.
box_abandon_release() { # message
  rm -f "$STACK_DIR/compose.yaml.next"
  die "$1"
}

# Bring a tag up, and either record it or put the previous one back.
box_release() { # tag previous
  local new="$1" previous="$2" repo
  say "Running now: ${previous:-nothing, this is the first deploy}"
  [ "$new" != "$previous" ] \
    || box_abandon_release "$new is already what .env names, so a failure would have nothing to roll back to. Nothing was changed on the box"

  step "Pulling $new on the box"
  for repo in $REPOSITORIES; do
    docker pull "$(image_ref "$repo" "$new")" \
      || box_abandon_release "the box could not pull $(image_ref "$repo" "$new")"
  done

  if [ -f "$STACK_DIR/compose.yaml" ] \
      && ! cp -p "$STACK_DIR/compose.yaml" "$STACK_DIR/compose.yaml.previous"; then
    box_abandon_release "could not keep a copy of $STACK_DIR/compose.yaml to roll back to. Nothing was changed"
  fi
  mv "$STACK_DIR/compose.yaml.next" "$STACK_DIR/compose.yaml" \
    || die "could not put the new compose.yaml in place. Nothing was brought up"

  step "Bringing it up (waiting up to ${WAIT_TIMEOUT}s for healthy)"
  if box_up "$new" && box_health; then
    box_set_tag "$new" || die "$new is running, but $STACK_DIR/.env still names ${previous:-no image}.
Fix it by hand on the box: in $STACK_DIR/.env (keep it mode 600), set
TRIALMATCH_API_IMAGE=$(image_ref trialmatchrx-api "$new")
TRIALMATCH_WEB_IMAGE=$(image_ref trialmatchrx-web "$new")"
    printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$new" >> "$STACK_DIR/deploys.log"
    rm -f "$STACK_DIR/compose.yaml.previous"
    say "$new is up and healthy, and .env names it"
    return 0
  fi

  step "$new did not come up healthy. The last of its logs:"
  box_compose "$new" logs --no-color --tail 50 api web || true
  if [ -f "$STACK_DIR/compose.yaml.previous" ] \
      && ! mv "$STACK_DIR/compose.yaml.previous" "$STACK_DIR/compose.yaml"; then
    say "WARN  could not put the previous compose.yaml back; the rollback uses the new one"
  fi
  if [ -z "$previous" ]; then
    box_compose "$new" down || true
    die "the first deploy failed, so there is no earlier image to put back; the new containers were stopped. .env is unchanged; see the logs above"
  fi
  step "Putting $previous back"
  if box_up "$previous" && box_health; then
    die "$new failed and was rolled back: $previous is running again, and .env still names it"
  fi
  die "$new failed, and $previous did not come back healthy either. Look at \`docker compose -f compose.yaml ps\` in $STACK_DIR"
}

# The tags to keep, space-separated with a trailing space: current, previous, then earlier
# deploys newest first by deploys.log (the order they ran in), until there are KEEP.
box_tags_to_keep() { # current previous
  {
    printf '%s\n%s\n' "$1" "$2"
    [ ! -f "$STACK_DIR/deploys.log" ] \
      || awk '{ line[NR] = $2 } END { for (i = NR; i > 0; i--) print line[i] }' "$STACK_DIR/deploys.log"
  } | awk -v keep="$KEEP" 'NF && !seen[$0]++ && n < keep { printf "%s ", $0; n++ }'
}

box_registry_repositories() {
  curl -fsS "$REGISTRY_URL/v2/_catalog" \
    | sed -n 's/.*"repositories":\[\([^]]*\)\].*/\1/p' | tr ',' '\n' | tr -d '" '
}

box_registry_tags() { # repository
  curl -fsS "$REGISTRY_URL/v2/$1/tags/list" \
    | sed -n 's/.*"tags":\[\([^]]*\)\].*/\1/p' | tr ',' '\n' | tr -d '" '
}

# "<digest> <content type>" for the manifest a tag names, or nothing. The Accept headers
# make the registry answer for the format it stores, whose digest is the one DELETE finds.
box_registry_manifest() { # repository tag
  local type accept=()
  for type in $IMAGE_TYPES $INDEX_TYPES; do accept+=(-H "Accept: $type"); done
  curl -fsS -I "${accept[@]}" "$REGISTRY_URL/v2/$1/manifests/$2" \
    | tr -d '\r' | awk '
        tolower($1) == "docker-content-digest:" { digest = $2 }
        tolower($1) == "content-type:" { type = $2 }
        END { if (digest != "") print digest, type }'
}

# Delete our tags but those to keep, collect the garbage, restart the registry.
#
# The registry is shared with KeyIDPro, and `garbage-collect --delete-untagged` works on all
# of it. Registry 2.8 counts an index's child manifests as untagged and deletes them, so a
# tag that is an index - in any repository - would stop pulling. So it refuses, before
# deleting anything, if any tag in the registry is one. Ours are pushed as plain manifests
# (--provenance=false --sbom=false).
box_prune_registry() { # tags-to-keep
  local keep="$1" repo tag manifest digest type kept_digests doomed failed=0

  for repo in $(box_registry_repositories); do
    for tag in $(box_registry_tags "$repo"); do
      manifest="$(box_registry_manifest "$repo" "$tag")"
      for type in $INDEX_TYPES; do
        if [ "${manifest#* }" = "$type" ]; then
          say "WARN  $repo:$tag is an index, and garbage-collect would delete what it points to. Not pruning the registry."
          return 1
        fi
      done
    done
  done

  for repo in $REPOSITORIES; do
    # Every digest before any delete. Two tags can name one manifest (an unchanged image
    # rebuilds to the same digest), and deleting by digest takes every tag that names it:
    # one being kept must keep it, and the rest go with a single DELETE.
    kept_digests='' doomed=''
    for tag in $keep; do
      manifest="$(box_registry_manifest "$repo" "$tag")"
      [ -z "$manifest" ] || kept_digests="$kept_digests ${manifest%% *}"
    done
    for tag in $(box_registry_tags "$repo"); do
      case " $keep" in *" $tag "*) continue ;; esac
      manifest="$(box_registry_manifest "$repo" "$tag")"
      digest="${manifest%% *}"
      if [ -z "$digest" ]; then say "WARN  no digest for $repo:$tag"; failed=1; continue; fi
      case "$kept_digests " in
        *" $digest "*) say "left $repo:$tag: it shares its manifest with a tag being kept"; continue ;;
      esac
      say "deleting $repo:$tag"
      case "$doomed " in *" $digest "*) ;; *) doomed="$doomed $digest" ;; esac
    done
    for digest in $doomed; do
      curl -fsS -X DELETE "$REGISTRY_URL/v2/$repo/manifests/$digest" >/dev/null \
        || { say "WARN  could not delete $repo@$digest"; failed=1; }
    done
  done

  # Safe while nothing pushes. box_prune holds REGISTRY_LOCK around this, which stops a second
  # TrialMatch deploy pruning at once; KeyIDPro's deploy doesn't take it yet.
  local gc_out
  if ! gc_out="$(docker exec "$REGISTRY_CONTAINER" registry garbage-collect --delete-untagged \
      /etc/docker/registry/config.yml 2>&1)"; then
    say "WARN  the registry's garbage-collect failed:"; printf '%s\n' "$gc_out" | tail -5; failed=1
  fi

  # Registry 2.8 caches blob descriptors in memory, which a separate garbage-collect does
  # not clear: without a restart the next push skips a deleted layer as "already exists".
  local tries=0
  if docker restart "$REGISTRY_CONTAINER" >/dev/null; then
    until curl -fsS -o /dev/null "$REGISTRY_URL/v2/"; do
      tries=$((tries + 1))
      if [ "$tries" -ge 30 ]; then
        say "WARN  the registry did not answer within 30s of restarting"; failed=1; break
      fi
      sleep 1
    done
  else
    say "WARN  could not restart the registry; restart it before the next push"; failed=1
  fi
  return "$failed"
}

# Only after a deploy that worked. A failure here is a warning: the new images are up.
box_prune() { # current previous
  local current="$1" previous="$2" repo image keep failed=0

  step "Pruning old images on the box"
  for repo in $REPOSITORIES; do
    for image in $(docker image ls --format '{{.Repository}}:{{.Tag}}' "$REGISTRY/$repo"); do
      case "$image" in *:'<none>') continue ;; "$REGISTRY/$repo:"*) ;; *) continue ;; esac
      case "${image##*:}" in "$current" | "$previous") continue ;; esac
      if docker rmi "$image" >/dev/null; then say "removed $image"; else say "WARN  could not remove $image"; failed=1; fi
    done
  done
  docker image prune -f >/dev/null || failed=1

  step "Pruning the registry to the newest $KEEP tags"
  keep="$(box_tags_to_keep "$current" "$previous")"
  say "keeping: $keep"
  # The lock is held on fd 9 for the subshell's life: delete, garbage-collect, restart. Held
  # elsewhere, this deploy's registry prune is skipped (75); the next deploy's catches up.
  local status=0
  ( flock -n 9 || exit 75; box_prune_registry "$keep" ) 9>>"$REGISTRY_LOCK" || status=$?
  case "$status" in
    0) ;;
    75) say "SKIP  $REGISTRY_LOCK is held by another prune; the registry was not pruned this time" ;;
    *) failed=1 ;;
  esac

  [ "$failed" = 0 ] || say "WARN  the deploy worked, but the prune did not finish; see above"
  return 0
}

# What the box is running, asked of the containers rather than read back from .env.
box_report() { # tag
  local service id
  step "Now running"
  for service in api web; do
    id="$(box_compose "$1" ps -q "$service")"
    say "$service: $(docker inspect --format '{{.Config.Image}}' "$id" 2>/dev/null || echo 'no container')"
  done
  box_compose "$1" ps
  step "Disk"
  df -h / || true
  step "Memory"
  free -m || true
}

BOX_FUNCTIONS='say step die image_ref box_env_value box_current_tag box_preflight
  box_stage_compose box_set_tag box_compose box_up box_health box_abandon_release
  box_release box_tags_to_keep
  box_registry_repositories box_registry_tags box_registry_manifest box_prune_registry
  box_prune box_report'

on_box() { # function [args...]
  {
    printf 'set -u -o pipefail\n'
    printf 'SCRIPT_NAME=%q STACK_DIR=%q REGISTRY=%q REGISTRY_URL=%q REGISTRY_CONTAINER=%q\n' \
      "${SCRIPT_NAME:-deploy}" "$STACK_DIR" "$REGISTRY" "$REGISTRY_URL" "$REGISTRY_CONTAINER"
    printf 'REGISTRY_LOCK=%q\n' "$REGISTRY_LOCK"
    printf 'KEEP=%q WAIT_TIMEOUT=%q REPOSITORIES=%q REQUIRED_ENV=%q\n' \
      "$KEEP" "$WAIT_TIMEOUT" "$REPOSITORIES" "$REQUIRED_ENV"
    printf 'IMAGE_TYPES=%q INDEX_TYPES=%q\n' "$IMAGE_TYPES" "$INDEX_TYPES"
    # shellcheck disable=SC2086  # a list of names, split on purpose
    declare -f $BOX_FUNCTIONS
    printf '%q ' "$@"
    printf '\n'
  } | ssh "$HOST" 'bash -s'
}

main() {
  set -euo pipefail

  local dry_run=''
  while [ $# -gt 0 ]; do
    case "$1" in
      # Lines 3-24 are the usage block.
      -h | --help) sed -n '3,24p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; return 0 ;;
      --dry-run) dry_run=yes ;;
      *) die "unknown option: $1 (see --help)" ;;
    esac
    shift
  done

  case "$KEEP" in
    '' | *[!0-9]* | 0 | 1) die "KEEP is '$KEEP'; it has to be at least 2, to hold the current images and the previous ones" ;;
  esac

  local changes commit tag
  changes="$(uncommitted)"
  commit="$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD)"
  [ -z "$changes" ] || die "uncommitted changes would go into the images built from $commit:
$changes
Commit or stash them first. Nothing was built."
  tag="$commit-$(date -u +%Y%m%d%H%M%S)"

  local api web
  api="$(image_ref trialmatchrx-api "$tag")"
  web="$(image_ref trialmatchrx-web "$tag")"

  if [ -n "$dry_run" ]; then
    step "Dry run: nothing built, nothing sent"
    say "would build  $api  (api/Dockerfile) for linux/amd64"
    say "would build  $web  (web/Dockerfile) for linux/amd64"
    say "would push both to $REGISTRY"
    say "would run them on $HOST in $STACK_DIR (compose.yaml only), rolling back on failure"
    say "would keep the newest $KEEP tags in the registry"
    return 0
  fi

  step "Checking $HOST before building"
  on_box box_preflight

  # Provenance and SBOM off, so each tag is one plain manifest, not an index (see
  # box_prune_registry). Built from the repo root: .dockerignore keeps .env and *.db out.
  step "Building $api for linux/amd64 and pushing it"
  docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
    -f "$REPO_ROOT/api/Dockerfile" -t "$api" --push "$REPO_ROOT"
  step "Building $web for linux/amd64 and pushing it"
  docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
    -f "$REPO_ROOT/web/Dockerfile" --build-arg NEXT_PUBLIC_API_URL= -t "$web" --push "$REPO_ROOT"

  step "Copying compose.yaml to $HOST:$STACK_DIR"
  on_box box_stage_compose "$(cat "$REPO_ROOT/compose.yaml")"

  local previous
  previous="$(on_box box_current_tag)"
  on_box box_release "$tag" "$previous"
  on_box box_prune "$tag" "$previous"
  on_box box_report "$tag"
}

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  main "$@"
fi
