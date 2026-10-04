#!/usr/bin/env bash
set -euo pipefail

# Regenerates docs/ops/e2e_reliability.log from GitHub's own public,
# unauthenticated REST API, instead of a hand-appended log.
#
# Why: with an intermittent e2e job, the FREQUENCY of failure (1 in
# 10 needs a different fix than 1 in 2) is itself the diagnosis — and
# that frequency is only trustworthy if every run is recorded, not
# just the ones a human remembered to log after watching a run finish.
# That discipline lapses within a week in practice. This script
# re-derives every row fresh from the API's own per-run job list for
# the last N completed runs, so the record can never silently fall
# behind just because nobody ran it by hand that day.
#
# What's preserved vs. re-derived: a hand-written diagnostic comment
# — one or more lines starting with "#", sitting directly above a
# given run's data line in the CURRENT log — is kept and carried
# forward unchanged on the next regeneration, keyed by that run's
# number. Everything else (timestamp, commit, result, the short
# machine-extracted reason) is re-derived from the API every time this
# runs, so it reflects whatever the e2e job's own annotation captured
# — not a one-time snapshot someone typed in.
#
# Unauthenticated GitHub REST calls are capped at 60/hour per IP.
# This script makes 1 + 2*N requests in the worst case (one per run
# for its job list, one more for each FAILED run's annotations) — keep
# N modest (default 20) unless you know the budget is free.
#
# Usage: scripts/e2e_history.sh [N]   (default N=20)

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_PATH="$REPO_DIR/docs/ops/e2e_reliability.log"
N="${1:-20}"

python3 - "$LOG_PATH" "$N" <<'PYEOF'
import datetime
import json
import sys
import urllib.error
import urllib.request

log_path, n = sys.argv[1], int(sys.argv[2])
REPO = "mateia924/CPS"

# --- 1. Preserve existing hand-written comment blocks, keyed by run number. ---
try:
    with open(log_path, encoding="utf-8") as f:
        existing_lines = f.read().splitlines()
except FileNotFoundError:
    existing_lines = []

existing_comments = {}
pending_comment = []
for line in existing_lines:
    if line.startswith("#"):
        pending_comment.append(line)
        continue
    if line.strip() == "":
        pending_comment = []
        continue
    fields = line.split("\t")
    if len(fields) >= 2 and pending_comment:
        existing_comments[fields[1]] = pending_comment
    pending_comment = []

# --- 2. Pull the last N completed runs and each one's "e2e" job. ---
def api_get(url):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            sys.exit(
                "e2e_history.sh: GitHub's unauthenticated rate limit (60/hour/IP) is "
                "exhausted. Check https://api.github.com/rate_limit for the reset time "
                "and re-run after it — no partial/corrupt write was made."
            )
        raise

runs_data = api_get(f"https://api.github.com/repos/{REPO}/actions/runs?per_page={min(n, 100)}")
runs = [r for r in runs_data["workflow_runs"] if r["status"] == "completed"]
runs.sort(key=lambda r: r["run_number"])

def utc_to_local(stamp):
    dt = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone(datetime.timedelta(hours=3))).strftime("%Y-%m-%dT%H:%M:%S+03:00")

out_lines = []
seen = 0
failed = 0
for r in runs:
    run_number = str(r["run_number"])
    jobs_data = api_get(f"https://api.github.com/repos/{REPO}/actions/runs/{r['id']}/jobs")
    e2e_job = next((j for j in jobs_data["jobs"] if j["name"] == "e2e"), None)
    if e2e_job is None:
        continue  # no e2e job on this run (predates it, or it never got scheduled)
    seen += 1

    result = (e2e_job.get("conclusion") or "unknown").upper()
    reason = ""
    if result != "SUCCESS":
        ann = api_get(f"https://api.github.com/repos/{REPO}/check-runs/{e2e_job['id']}/annotations?per_page=100")
        messages = [a["message"] for a in ann if a.get("title", "").startswith("e2e (Playwright) failed")]
        if not messages:
            # Pre-dates the targeted annotation (2026-10-04) — fall back to
            # whatever's there, minus pure npm version noise.
            messages = [a["message"] for a in ann if "npm notice" not in a.get("message", "") and a.get("message", "").strip()]
        reason = " | ".join(messages).replace("\n", " ")[:500] if messages else "unknown — no usable annotation captured"
        if result == "FAILURE":
            failed += 1

    ts = utc_to_local(r["updated_at"])
    if run_number in existing_comments:
        out_lines.extend(existing_comments[run_number])
    out_lines.append(f"{ts}\t{run_number}\t{r['head_sha']}\te2e job\t{result}\t{reason}")

with open(log_path, "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines) + "\n")

print(f"regenerated {log_path}: {seen} run(s) with an e2e job, {failed} FAILURE")
PYEOF
