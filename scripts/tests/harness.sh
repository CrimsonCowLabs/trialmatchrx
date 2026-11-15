#!/usr/bin/env bash
#
# The assertions and stubbing the script test suites are written in.
#
#   . "$(dirname "${BASH_SOURCE[0]}")/harness.sh"
#
# Nothing here depends on anything beyond bash 3.2 and what macOS already
# ships, which is the rule the suites themselves keep: anyone who cloned the
# repo can run them without first running the thing under test.
#
# A failing assertion counts and carries on rather than exiting, so one broken
# behaviour reports alongside everything else that still works instead of
# hiding the rest of the run behind itself. The counters live here; each suite
# prints its own summary with finish_up at the bottom of the file.

PASSED=0
FAILED=0

# --- assertions ---------------------------------------------------------

ok()   { PASSED=$((PASSED + 1)); printf '  ok    %s\n' "$1"; }
bad()  { FAILED=$((FAILED + 1)); printf '  FAIL  %s\n' "$1"
         [ -n "${2:-}" ] && printf '        %s\n' "$2"; return 0; }
skip() { printf '  skip  %s (%s)\n' "$1" "${2:-}"; }

assert_contains() { # haystack needle label
  case "$1" in
    *"$2"*) ok "$3" ;;
    *) bad "$3" "expected to find '$2' in: $(printf '%s' "$1" | head -c 400)" ;;
  esac
}

assert_missing() { # haystack needle label
  case "$1" in
    *"$2"*) bad "$3" "found '$2' in: $(printf '%s' "$1" | head -c 400)" ;;
    *) ok "$3" ;;
  esac
}

assert_equals() { # actual expected label
  if [ "$1" = "$2" ]; then ok "$3"; else bad "$3" "got '$1', wanted '$2'"; fi
}

assert_status() { # actual expected label
  if [ "$1" = "$2" ]; then ok "$3"; else bad "$3" "exit status $1, wanted $2"; fi
}

section() { printf '\n%s\n' "$1"; }

# --- fixtures -----------------------------------------------------------

# A PATH holding only what we put in it, so "missing tool" is a real absence
# rather than a version this machine happens not to have.
sandbox_path() { printf '%s:/usr/bin:/bin:/usr/sbin:/sbin' "$1"; }

stub_bin() { # dir name output [exit]
  mkdir -p "$1"
  cat > "$1/$2" <<STUB
#!/bin/sh
printf '%s\n' "$3"
exit ${4:-0}
STUB
  chmod +x "$1/$2"
}

# --- the summary a suite ends on ----------------------------------------

# Returns nonzero when anything failed, so `finish_up` as the last line of a
# suite is also that suite's exit status.
finish_up() {
  printf '\n%s\n' "-----"
  printf '%d passed, %d failed\n' "$PASSED" "$FAILED"
  [ "$FAILED" -eq 0 ]
}
