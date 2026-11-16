#!/usr/bin/env bash
#
# Tests for scripts/deploy-main.sh.
#
#   bash scripts/tests/test-deploy-main.sh
#
# Same rules as test-deploy.sh: bash 3.2 and what macOS ships, no network, no Docker, no
# box. The real git runs against a local bare repo standing in for origin; its main carries
# a fake scripts/deploy.sh that records the commit it ran from, its arguments and whether
# its checkout was clean, so the tests see exactly what the real deploy would have built.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# shellcheck source=/dev/null
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/harness.sh"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/deploy-main-tests.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

g() { git -c user.name=test -c user.email=test@example.com -c init.defaultBranch=main "$@"; }

# origin: a bare repo whose main has the fake deploy.sh.
g init --quiet --bare "$WORK/origin.git"
g clone --quiet "$WORK/origin.git" "$WORK/seed" 2>/dev/null
mkdir -p "$WORK/seed/scripts"
cat > "$WORK/seed/scripts/deploy.sh" <<STUB
#!/usr/bin/env bash
here="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)"
{
  printf 'commit=%s\n' "\$(git -C "\$here" rev-parse HEAD)"
  printf 'args=%s\n' "\$*"
  printf 'dirty=%s\n' "\$(git -C "\$here" status --porcelain)"
  printf 'host=%s\n' "\${HOST:-}"
} > "$WORK/deploy-ran"
exit \${FAKE_DEPLOY_STATUS:-0}
STUB
chmod +x "$WORK/seed/scripts/deploy.sh"
echo one > "$WORK/seed/app.txt"
g -C "$WORK/seed" add -A && g -C "$WORK/seed" commit --quiet -m "main one"
g -C "$WORK/seed" push --quiet origin main

# here: a checkout of origin, on a feature branch with uncommitted work, carrying the
# script under test.
g clone --quiet "$WORK/origin.git" "$WORK/here" 2>/dev/null
mkdir -p "$WORK/here/scripts"
cp "$REPO_ROOT/scripts/deploy-main.sh" "$WORK/here/scripts/deploy-main.sh"
g -C "$WORK/here" checkout --quiet -b feature
echo feature > "$WORK/here/app.txt"
g -C "$WORK/here" commit --quiet -am "feature work"
echo uncommitted > "$WORK/here/app.txt"

# main moves on after the clone, so a stale local main would be caught.
echo two > "$WORK/seed/app.txt"
g -C "$WORK/seed" commit --quiet -am "main two"
g -C "$WORK/seed" push --quiet origin main
LATEST="$(g -C "$WORK/seed" rev-parse HEAD)"

run() { # [args...] -> $OUT, $STATUS
  rm -f "$WORK/deploy-ran"
  OUT="$(cd "$WORK/here" && bash scripts/deploy-main.sh "$@" 2>&1)"
  STATUS=$?
}

ran() { sed -n "s/^$1=//p" "$WORK/deploy-ran" 2>/dev/null; }

worktrees() { g -C "$WORK/here" worktree list | wc -l | tr -d ' '; }

section "deploys the latest main, not the current branch"
run --dry-run
assert_status "$STATUS" 0 "exits 0"
assert_equals "$(ran commit)" "$LATEST" "runs deploy.sh from the fetched main"
assert_equals "$(ran args)" "--dry-run" "passes the arguments on"
assert_equals "$(ran dirty)" "" "the checkout it deploys from is clean"
assert_contains "$OUT" "main two" "says which commit it deploys"
assert_equals "$(g -C "$WORK/here" rev-parse --abbrev-ref HEAD)" "feature" "leaves this checkout on its branch"
assert_equals "$(cat "$WORK/here/app.txt")" "uncommitted" "leaves this checkout's changes alone"
assert_equals "$(worktrees)" "1" "removes its worktree afterwards"

section "with no arguments"
run
assert_status "$STATUS" 0 "exits 0 (bash 3.2 and an empty argument list)"
assert_equals "$(ran args)" "" "passes nothing on"

section "settings pass through to deploy.sh"
HOST=someone@elsewhere run
assert_equals "$(ran host)" "someone@elsewhere" "HOST reaches deploy.sh"

section "a failed deploy"
FAKE_DEPLOY_STATUS=3 run
assert_status "$STATUS" 3 "exits with deploy.sh's status"
assert_equals "$(worktrees)" "1" "still removes its worktree"

section "a branch that doesn't exist"
BRANCH=no-such-branch run
assert_status "$STATUS" 1 "exits 1"
assert_contains "$OUT" "could not fetch origin no-such-branch" "says what it couldn't fetch"
assert_equals "$(ran commit)" "" "runs no deploy"

section "--help"
run --help
assert_status "$STATUS" 0 "exits 0"
assert_contains "$OUT" "Deploy the latest main" "prints the usage"
assert_equals "$(ran commit)" "" "runs no deploy"

finish_up
