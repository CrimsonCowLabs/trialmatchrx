#!/usr/bin/env bash
#
# Deploy the latest main, whatever is checked out here. `make deploy` runs this:
#
#   ./scripts/deploy-main.sh [--dry-run]
#
#   --help          this text
#   --dry-run       passed on to scripts/deploy.sh: say what would be built, and stop
#
#   REMOTE=origin   where main is fetched from
#   BRANCH=main     the branch to deploy
#
# Fetches REMOTE/BRANCH, checks it out detached in a temporary worktree, and runs that
# commit's own scripts/deploy.sh there, so the images are built from exactly the fetched
# commit: not from the current branch, and never with this checkout's uncommitted changes.
# Every other setting of deploy.sh (HOST, KEEP, ...) passes through the environment. The
# worktree is removed when this exits, whether the deploy worked or not.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

: "${REMOTE:=origin}"
: "${BRANCH:=main}"

die() { printf '\ndeploy-main: %s\n' "$*" >&2; exit 1; }

main() {
  set -euo pipefail

  case "${1:-}" in
    # Lines 3-16 are the usage block.
    -h | --help) sed -n '3,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; return 0 ;;
  esac

  printf '\n==> Fetching %s/%s\n' "$REMOTE" "$BRANCH"
  git -C "$REPO_ROOT" fetch --quiet "$REMOTE" "$BRANCH" \
    || die "could not fetch $REMOTE $BRANCH. Nothing was built."
  local commit
  commit="$(git -C "$REPO_ROOT" rev-parse --verify --quiet "FETCH_HEAD^{commit}")" \
    || die "$REMOTE $BRANCH did not resolve to a commit. Nothing was built."

  local dir
  : "${TMPDIR:=/tmp}"
  dir="$(mktemp -d "${TMPDIR%/}/trialmatchrx-deploy.XXXXXX")"
  # mktemp made the directory; worktree add wants to make it itself.
  rmdir "$dir"
  # shellcheck disable=SC2064  # expand now: $dir is local to main
  trap "git -C '$REPO_ROOT' worktree remove --force '$dir' 2>/dev/null || rm -rf '$dir'" EXIT
  git -C "$REPO_ROOT" worktree add --quiet --detach "$dir" "$commit" \
    || die "could not check out $commit in $dir. Nothing was built."
  printf '  deploying %s (%s/%s) from %s\n' "$(git -C "$dir" log -1 --format='%h %s')" \
    "$REMOTE" "$BRANCH" "$dir"

  [ -x "$dir/scripts/deploy.sh" ] || die "$commit has no executable scripts/deploy.sh"
  "$dir/scripts/deploy.sh" ${@+"$@"}  # bash 3.2: a bare "$@" is unbound under set -u
}

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  main "$@"
fi
