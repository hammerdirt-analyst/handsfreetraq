import pytest

from service_router import classify_service

# Helper to assert the pair succinctly

def assert_route(text, expected_service, expected_section=None):
    service, section = classify_service(text)
    assert service == expected_service, f"{text!r} → expected {expected_service}, got {service}"
    assert section == expected_section, f"{text!r} → expected section {expected_section}, got {section}"


class TestServiceRouter:
    # ------------------------- CORRECTIONS -------------------------
    @pytest.mark.parametrize(
        "text,expected_section",
        [
            ("set dbh to 30 inches", "tree_description"),  # field hint → tree_description
            ("remove driveway from targets", "targets"),     # explicit section token
            ("replace likelihood with 'unlikely' in risks", "risks"),
        ],
    )
    def test_make_correction_with_section(self, text, expected_section):
        assert_route(text, "MAKE_CORRECTION", expected_section)

    def test_make_correction_assignment_without_section(self):
        # Assignment phrasing but no clear section hint → still a correction, section=None
        assert_route("change value to 42", "MAKE_CORRECTION", None)

    # --------------------- SECTION SUMMARY (PROSE) -----------------
    @pytest.mark.parametrize(
        "text,expected_section",
        [
            ("recap the targets", "targets"),
            ("brief summary of tree description", "tree_description"),
            ("overview of the recommendations section", "recommendations"),
        ],
    )
    def test_section_summary_prose(self, text, expected_section):
        assert_route(text, "SECTION_SUMMARY", expected_section)

    @pytest.mark.parametrize("text", [
        "executive summary",
        "brief summary",
        "overall summary",
        "recap",
    ])
    def test_section_summary_without_section_is_none(self, text):
        # Prose cues without a section should not assume OUTLINE; return NONE → Coordinator clarifies
        assert_route(text, "NONE", None)

    # ----------------------------- OUTLINE ------------------------
    def test_outline_with_section_routes_to_section_summary(self):
        # Explicit outline + section → SECTION_SUMMARY for that section (Coordinator chooses outline mode)
        assert_route("outline the risks", "SECTION_SUMMARY", "risks")
        assert_route("please outline targets section", "SECTION_SUMMARY", "targets")

    def test_outline_without_section_routes_to_outline(self):
        # Explicit outline without section → OUTLINE (Coordinator defaults to current_section)
        assert_route("outline the report", "OUTLINE", None)
        assert_route("overall outline please", "OUTLINE", None)
        assert_route("outline", "OUTLINE", None)

    # --------------------------- REPORT DRAFT ---------------------
    @pytest.mark.parametrize("text", [
        "draft the report",
        "generate a report",
        "prepare my report",
        "create the report draft",
        "compile a report",
    ])
    def test_report_draft_detection(self, text):
        assert_route(text, "MAKE_REPORT_DRAFT", None)

    # ---------------------------- NEGATIVES -----------------------
    def test_report_outline_not_misrouted_to_draft(self):
        assert_route("report outline", "OUTLINE", None)

    def test_no_match_yields_none(self):
        assert_route("can you help?", "NONE", None)
