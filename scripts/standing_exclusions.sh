# shellcheck shell=bash
# The standing exclusion list (owner decisions): paths that are dirty on
# purpose and never committed. One definition, two readers (2026-10-19):
#   - scripts/precommit_guard.sh refuses a commit that stages one of them;
#   - scripts/deploy.sh does not count them as a dirty working tree.
# Before, only the pre-commit guard had the list, so every deploy was
# refused by these same files and answered with a stash or the
# ALLOW_DIRTY_DEPLOY escape hatch.
# Explicit paths only: an entry ending in "/" covers that one directory,
# any other entry exactly one file. No globs, no patterns.
CPS_STANDING_EXCLUSIONS=(
  "infra/fail2ban/"
  "docs/ops/backups.log"
  "docs/ops/ci-local.log"
  "frontend/next-env.d.ts"
  "docs/uat/screens/6.5.8/"
)

# Prints the entry that covers $1 and returns 0, or returns 1.
cps_standing_exclusion() {
  local path="$1" excluded
  for excluded in "${CPS_STANDING_EXCLUSIONS[@]}"; do
    case "$excluded" in
      */) [[ "$path" == "$excluded"* ]] || continue ;;
      *) [ "$path" = "$excluded" ] || continue ;;
    esac
    echo "$excluded"
    return 0
  done
  return 1
}
