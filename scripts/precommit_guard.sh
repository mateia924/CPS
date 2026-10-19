#!/usr/bin/env bash
set -euo pipefail

# Rule 50 (docs/SYSTEM_ANALYSIS.md §4), 2026-10-19: the git pre-commit
# guard (.githooks/pre-commit runs this; `git config core.hooksPath
# .githooks` wires it). It is what makes `git commit`/`git push` safe to
# run without a prompt: a commit that stages any of the following is
# refused, loudly, before it exists:
#   1. a path on the standing exclusion list (scripts/standing_exclusions.sh) — added,
#      modified or deleted;
#   2. a secret in a staged ADDED line: a password/secret/api_key/token
#      with a literal value, a private key header, or an email address
#      whose domain is not *.test (staging's *.staging.test included);
#   3. a new file (not in HEAD) larger than 1 MB.
# Only the lines a commit adds are scanned, not whole files: lines already
# in HEAD were published with it, and a rule that refused every later
# commit touching such a file would be switched off within a week.
# It prints path and line number ONLY, never the matched value — the
# terminal, Claude Code's session log and CI output are all places a
# printed secret would land (rule 50, "no secret in the output").
#
# Usage: scripts/precommit_guard.sh   (from inside the repo; reads the index)
# Exit 0 = nothing found; 1 = refused (each finding on stderr).

MAX_NEW_FILE_BYTES=1048576

cd "$(git rev-parse --show-toplevel)"
# The exclusion list lives in one file, also read by deploy.sh.
source scripts/standing_exclusions.sh
GIT=(git -c core.quotePath=false)
FINDINGS=()

# 1. Exclusion list — every staged path, deletions included.
while IFS= read -r -d '' path; do
  if excluded="$(cps_standing_exclusion "$path")"; then
    FINDINGS+=("$path: on the standing exclusion list ($excluded)")
  fi
done < <("${GIT[@]}" diff --cached --name-only --no-renames -z)

# 3. New files over 1 MB (a path HEAD already tracks may keep growing).
HAS_HEAD=1
git rev-parse --verify -q HEAD >/dev/null || HAS_HEAD=0
while IFS= read -r -d '' path; do
  if [ "$HAS_HEAD" = 1 ] && git cat-file -e "HEAD:$path" 2>/dev/null; then
    continue
  fi
  size="$(git cat-file -s ":$path")"
  if [ "$size" -gt "$MAX_NEW_FILE_BYTES" ]; then
    FINDINGS+=("$path: new file of $size bytes, over the 1 MB limit for files not already tracked")
  fi
done < <("${GIT[@]}" diff --cached --name-only --no-renames --diff-filter=A -z)

# 2. Secrets in added lines. awk tracks each hunk's new-file line number
# and prints "path:line: kind" — the value never leaves awk.
# Literal value = a quoted string of 4+ characters with no $ { < (not a
# variable, template or placeholder), or, on an unindented env-style
# line (KEY=value, upper-case key), any bare value not starting with $.
while IFS= read -r finding; do
  FINDINGS+=("$finding")
done < <("${GIT[@]}" diff --cached --no-renames --no-color -U0 --diff-filter=ACM | awk '
  BEGIN {
    key = "[A-Za-z0-9_]*([Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd]|[Pp][Aa][Ss][Ss][Ww][Dd]|[Ss][Ee][Cc][Rr][Ee][Tt]|[Aa][Pp][Ii]_?[Kk][Ee][Yy]|[Tt][Oo][Kk][Ee][Nn])[A-Za-z0-9_]*"
    quoted_literal = key "[\"'"'"']?[ \t]*[:=][ \t]*[\"'"'"'][^\"'"'"'$<{]{4,}[\"'"'"']"
    env_literal = "^(export[ \t]+)?[A-Z0-9_]*(PASSWORD|PASSWD|SECRET|API_KEY|APIKEY|TOKEN)[A-Z0-9_]*=[^$ \t\"'"'"'][^ \t]*$"
    private_key = "-----BEGIN [A-Z ]*PRIVATE KEY( BLOCK)?-----"
    email = "[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\\.[A-Za-z0-9-]+)*\\.[A-Za-z]+"
  }
  /^\+\+\+ / { path = substr($0, 7); next }
  /^@@ / {
    split($3, range, ",")
    line = substr(range[1], 2) + 0
    next
  }
  /^\+/ {
    text = substr($0, 2)
    if (text ~ quoted_literal || text ~ env_literal) print path ":" line ": credential with a literal value"
    if (text ~ private_key) print path ":" line ": private key header"
    rest = text
    while (match(rest, email)) {
      address = substr(rest, RSTART, RLENGTH)
      domain = tolower(substr(address, index(address, "@") + 1))
      if (domain !~ /\.test$/) { print path ":" line ": email address outside *.test"; break }
      rest = substr(rest, RSTART + RLENGTH)
    }
    line++
  }
')

if [ "${#FINDINGS[@]}" -gt 0 ]; then
  {
    echo
    echo "!!! COMMIT REFUSED by scripts/precommit_guard.sh (rule 50) — ${#FINDINGS[@]} finding(s):"
    for finding in "${FINDINGS[@]}"; do
      echo "  $finding"
    done
    echo "Unstage the path (git restore --staged <path>) or remove the value, then commit again."
    echo
  } >&2
  exit 1
fi
