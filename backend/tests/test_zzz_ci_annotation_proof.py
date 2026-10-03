"""Sprint 7.0 (CI #62/#63 investigation, rule 11): a deliberate,
temporary failure proving the ::error:: annotation mechanism on the
"Tests (pytest) — accounting" step actually fires on a real GitHub
Actions run (set +e / PIPESTATUS fix) — not assumed working because
it "looks right" on paper, the exact mistake rule 11 exists to catch.
Removed in the very next commit once confirmed: (1) the job shows red,
(2) this message is actually visible via the check-runs annotations
API, not just buried in a log no one reads.
"""


def test_ci_annotation_mechanism_deliberately_fails_for_proof():
    assert False, "CI #62/#63 rule-11 proof: deliberate failure to confirm ::error:: annotations actually fire — remove this file in the next commit once confirmed."
