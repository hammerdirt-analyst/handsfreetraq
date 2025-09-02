# tests/unit/test_service_router.py
"""
Deterministic service router unit tests.

What is tested
--------------
- MAKE_CORRECTION: common “change/set/update/…” phrasings with optional section hints.
- SECTION_SUMMARY: summary/overview/recap cues + section inference.
- QUICK_SUMMARY: whole-report quick/brief/overall/at-a-glance cues (no section).
- MAKE_REPORT_DRAFT: draft/build/generate/produce report cues (no section).
- NONE: benign chatter that should not route to a service.

Why this matters
----------------
The Coordinator must short-circuit to the deterministic router first; only when
it returns ("NONE", None) should the LLM backstop run. These tests lock the
deterministic contract.

File dependencies
-----------------
- service_router.classify_service (system under test)
"""

import pytest

from service_router import classify_service  # deterministic router only

# ----------------------------
# Parametrized deterministic cases
# ----------------------------

CASES_MAKE_CORRECTION = [
    ("update targets: playground occupied daily", ("MAKE_CORRECTION", "targets")),
    ("fix the recommendation: removal", ("MAKE_CORRECTION", "recommendations")),
    ("adjust risks to moderate likelihood", ("MAKE_CORRECTION", "risks")),
    ("replace the site use with residential", ("MAKE_CORRECTION", "area_description")),
    ("amend the target proximity to within strike potential", ("MAKE_CORRECTION", "targets")),
    ("edit tree description species to American Elm", ("MAKE_CORRECTION", "tree_description")),
    ("change the crown shape to vase", ("MAKE_CORRECTION", "tree_description")),
    ("correct area description: context should be commercial", ("MAKE_CORRECTION", "area_description")),
    ("please update risks severity to high", ("MAKE_CORRECTION", "risks")),
    ("modify recommendations: pruning scope is crown clean", ("MAKE_CORRECTION", "recommendations")),
    ("revise targets label to parking lot", ("MAKE_CORRECTION", "targets")),
    ("set tree description dbh to 28 inches", ("MAKE_CORRECTION", "tree_description")),
    ("switch site use to residential", ("MAKE_CORRECTION", "area_description")),
    ("make the risks rationale 'history of limb failures'", ("MAKE_CORRECTION", "risks")),
    ("update: recommendations should be removal", ("MAKE_CORRECTION", "recommendations")),
    ("please set occupied frequency to daily for the walkway target", ("MAKE_CORRECTION", "targets")),
    ("adjust tree description: type_common American Elm", ("MAKE_CORRECTION", "tree_description")),
    ("correct the area description context to residential", ("MAKE_CORRECTION", "area_description")),
    ("edit the risks rationale to 'history of limb failures'", ("MAKE_CORRECTION", "risks")),
    ("set recommendations.pruning.scope to 'crown clean'", ("MAKE_CORRECTION", "recommendations")),
    ("change targets: parking lot occupied daily", ("MAKE_CORRECTION", "targets")),
    ("change dbh to 30 inches", ("MAKE_CORRECTION", "tree_description")),
    ("fix the height to 45 feet", ("MAKE_CORRECTION", "tree_description")),
    ("set targets proximity to within strike potential", ("MAKE_CORRECTION", "targets")),
    ("make site use equal to residential", ("MAKE_CORRECTION", "area_description")),
    ("alter tree description species to Red Oak", ("MAKE_CORRECTION", "tree_description")),
    # robustness: spacing/case/punctuation
    ("Change DBH to 30 inches.", ("MAKE_CORRECTION", "tree_description")),
    (" please   update  risks: severity = high ", ("MAKE_CORRECTION", "risks")),
]

CASES_SECTION_SUMMARY = [
    ("tree description section summary", ("SECTION_SUMMARY", "tree_description")),
    ("summary of the recommendations section", ("SECTION_SUMMARY", "recommendations")),
    ("targets section summary", ("SECTION_SUMMARY", "targets")),
    ("give me a recommendations section summary", ("SECTION_SUMMARY", "recommendations")),
    ("TL;DR of the targets section", ("SECTION_SUMMARY", "targets")),
    ("rollup / summary of the area description section", ("SECTION_SUMMARY", "area_description")),
    ("please summarize the tree_description section", ("SECTION_SUMMARY", "tree_description")),
    ("provide a section summary for risks", ("SECTION_SUMMARY", "risks")),
    ("recap the area_description section", ("SECTION_SUMMARY", "area_description")),
    ("give me the risks section summary", ("SECTION_SUMMARY", "risks")),
    ("section summary: targets", ("SECTION_SUMMARY", "targets")),
    ("high-level summary of the recommendations section", ("SECTION_SUMMARY", "recommendations")),
    ("rollup of the tree_description section", ("SECTION_SUMMARY", "tree_description")),
    ("brief section summary for area_description", ("SECTION_SUMMARY", "area_description")),
    ("section recap: risks", ("SECTION_SUMMARY", "risks")),
    ("outline the targets section", ("SECTION_SUMMARY", "targets")),
    ("overview of recommendations section", ("SECTION_SUMMARY", "recommendations")),
    ("synopsis of tree description section", ("SECTION_SUMMARY", "tree_description")),
    ("summarize the area description section", ("SECTION_SUMMARY", "area_description")),
    ("give me a risks section recap", ("SECTION_SUMMARY", "risks")),
    ("condensed summary of targets section", ("SECTION_SUMMARY", "targets")),
    ("quick recap of recommendations section", ("SECTION_SUMMARY", "recommendations")),
    ("please TL;DR the tree_description section", ("SECTION_SUMMARY", "tree_description")),
    ("roll up the area_description section", ("SECTION_SUMMARY", "area_description")),
    ("section summary requested: risks", ("SECTION_SUMMARY", "risks")),
    # “overview” variants that previously failed
    ("tree description section overview", ("SECTION_SUMMARY", "tree_description")),
    ("targets section overview", ("SECTION_SUMMARY", "targets")),
    ("overview the area_description section", ("SECTION_SUMMARY", "area_description")),
    ("section overview: targets", ("SECTION_SUMMARY", "targets")),
    ("section overview: risks", ("SECTION_SUMMARY", "risks")),
    ("describe the targets section", ("SECTION_SUMMARY", "targets")),
    ("summary of recommendations section", ("SECTION_SUMMARY", "recommendations")),
    ("breakdown of tree description section", ("SECTION_SUMMARY", "tree_description")),
    ("overview the area description section", ("SECTION_SUMMARY", "area_description")),
    ("provide me a risks section overview", ("SECTION_SUMMARY", "risks")),
    ("brief summary of targets section", ("SECTION_SUMMARY", "targets")),
    ("section overview requested: risks", ("SECTION_SUMMARY", "risks")),
    # robustness: case/punctuation
    ("Overview of the Targets Section.", ("SECTION_SUMMARY", "targets")),
]

CASES_QUICK_SUMMARY = [
    ("give me a quick status summary", ("QUICK_SUMMARY", None)),
    ("short summary of the current state", ("QUICK_SUMMARY", None)),
    ("summary please (quick)", ("QUICK_SUMMARY", None)),
    ("condensed overall summary", ("QUICK_SUMMARY", None)),
    ("summarize what we have so far (quick)", ("QUICK_SUMMARY", None)),
    ("overall summary of progress", ("QUICK_SUMMARY", None)),
    ("brief status update", ("QUICK_SUMMARY", None)),
    ("quick recap please", ("QUICK_SUMMARY", None)),
    ("high-level summary please", ("QUICK_SUMMARY", None)),
    ("short recap of the state", ("QUICK_SUMMARY", None)),
    ("quick snapshot summary", ("QUICK_SUMMARY", None)),
    ("give me the overall TL;DR", ("QUICK_SUMMARY", None)),
    ("fast summary of current info", ("QUICK_SUMMARY", None)),
    ("concise summary please", ("QUICK_SUMMARY", None)),
    ("speedy status summary", ("QUICK_SUMMARY", None)),
    ("quick overview", ("QUICK_SUMMARY", None)),
    ("overall recap", ("QUICK_SUMMARY", None)),
    ("brief rollup", ("QUICK_SUMMARY", None)),
    ("short overview", ("QUICK_SUMMARY", None)),
    ("quick state-of-play", ("QUICK_SUMMARY", None)),
    ("status at a glance", ("QUICK_SUMMARY", None)),
    ("TL;DR overall", ("QUICK_SUMMARY", None)),
    ("what's the quick status", ("QUICK_SUMMARY", None)),
    ("quick brief", ("QUICK_SUMMARY", None)),
    ("topline summary", ("QUICK_SUMMARY", None)),
    # more that previously failed
    ("brief summary of the current state", ("QUICK_SUMMARY", None)),
    ("summarize what we have currently (quick)", ("QUICK_SUMMARY", None)),
    ("complete summary of progress", ("QUICK_SUMMARY", None)),
    ("fast recap please", ("QUICK_SUMMARY", None)),
    ("brief recap of the current state", ("QUICK_SUMMARY", None)),
    ("provide me the overall TL;DR", ("QUICK_SUMMARY", None)),
    ("quick summary of current information", ("QUICK_SUMMARY", None)),
    ("rapid status summary", ("QUICK_SUMMARY", None)),
    ("fast overview", ("QUICK_SUMMARY", None)),
    ("complete recap", ("QUICK_SUMMARY", None)),
    ("quick rollup", ("QUICK_SUMMARY", None)),
    ("brief overview", ("QUICK_SUMMARY", None)),
    ("status overview", ("QUICK_SUMMARY", None)),
    ("TL;DR complete", ("QUICK_SUMMARY", None)),
    ("fast brief", ("QUICK_SUMMARY", None)),
    ("executive summary", ("QUICK_SUMMARY", None)),
    # robustness
    ("Quick Overview.", ("QUICK_SUMMARY", None)),
]

CASES_REPORT_DRAFT = [
    ("please draft a report", ("MAKE_REPORT_DRAFT", None)),
    ("can you generate a report draft", ("MAKE_REPORT_DRAFT", None)),
    ("I’d like you to build a report", ("MAKE_REPORT_DRAFT", None)),
    ("produce the final report", ("MAKE_REPORT_DRAFT", None)),
    ("prepare my report now", ("MAKE_REPORT_DRAFT", None)),
    ("let’s draft this report", ("MAKE_REPORT_DRAFT", None)),
    ("generate a draft report write-up", ("MAKE_REPORT_DRAFT", None)),
    ("build a preliminary report", ("MAKE_REPORT_DRAFT", None)),
    ("produce a report", ("MAKE_REPORT_DRAFT", None)),
    ("make the report now", ("MAKE_REPORT_DRAFT", None)),
    ("assemble a report draft", ("MAKE_REPORT_DRAFT", None)),
    ("create the report draft", ("MAKE_REPORT_DRAFT", None)),
    ("start a report draft", ("MAKE_REPORT_DRAFT", None)),
    ("compile a report", ("MAKE_REPORT_DRAFT", None)),
    ("spin up a report draft", ("MAKE_REPORT_DRAFT", None)),
    ("initiate the report draft", ("MAKE_REPORT_DRAFT", None)),
    ("draft the report for me", ("MAKE_REPORT_DRAFT", None)),
    ("generate the report", ("MAKE_REPORT_DRAFT", None)),
    ("prepare a draft report", ("MAKE_REPORT_DRAFT", None)),
    ("put together a report", ("MAKE_REPORT_DRAFT", None)),
    ("create a report now", ("MAKE_REPORT_DRAFT", None)),
    ("produce a draft write-up (report)", ("MAKE_REPORT_DRAFT", None)),
    ("get me a report draft", ("MAKE_REPORT_DRAFT", None)),
    ("start drafting the report", ("MAKE_REPORT_DRAFT", None)),
    ("write a report draft", ("MAKE_REPORT_DRAFT", None)),
    ("construct a report", ("MAKE_REPORT_DRAFT", None)),
    ("assemble a report", ("MAKE_REPORT_DRAFT", None)),
]

CASES_NEGATIVE = [
    ("hello there", ("NONE", None)),
    ("what time is it", ("NONE", None)),
    ("i like trees", ("NONE", None)),
    ("thanks", ("NONE", None)),
    # near-misses that should NOT route
    ("risks are moderate today", ("NONE", None)),            # descriptive, no service cue
    ("targets look fine", ("NONE", None)),
    ("reportedly windy", ("NONE", None)),                     # 'report' substring
]

ALL_CASES = (
    CASES_MAKE_CORRECTION
    + CASES_SECTION_SUMMARY
    + CASES_QUICK_SUMMARY
    + CASES_REPORT_DRAFT
    + CASES_NEGATIVE
)

@pytest.mark.parametrize(
    "text,expected",
    ALL_CASES,
    ids=[f"{exp[0]}::{(exp[1] or 'none')}::{i}" for i, (_, exp) in enumerate(ALL_CASES, 1)],
)
def test_service_router_deterministic(text, expected):
    got = classify_service(text)
    assert got == expected, f"\ntext: {text}\nexpected: {expected}\n     got: {got}\n"
