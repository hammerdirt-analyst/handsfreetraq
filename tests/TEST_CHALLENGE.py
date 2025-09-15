CHALLENGING_TEST_CASES = [
    # Multiple scopes in one phrase
    ("update targets proximity and tree description height to 60 feet", "MAKE_CORRECTION", "targets"),
    # Multiple sections
    ("correct area description context to commercial; also fix recommendations pruning scope", "MAKE_CORRECTION",
     "area_description"),
    ("change targets: playground daily and risks: high severity with structural concerns", "MAKE_CORRECTION",
     "targets"),
    ("modify tree description: dbh 35 inches, height 55 feet in recommendations: remove immediately", "MAKE_CORRECTION",
     "tree_description"),
    ("adjust risks rationale to 'decay detected' and update targets proximity beyond falling range", "MAKE_CORRECTION",
     "risks"),

    # Ambiguous section references
    ("update the description to include more detail about risk factors", "MAKE_CORRECTION", None),
    # Could be tree_description or area_description
    ("change the target area usage frequency", "MAKE_CORRECTION", "targets"),  # "target area" - tricky parsing
    ("modify risk assessment severity level", "MAKE_CORRECTION", "risks"),  # "risk assessment" vs "risks"
    ("correct description of commercial usage", "MAKE_CORRECTION", None),  # Ambiguous which description
    ("update target recommendations for pruning", "MAKE_CORRECTION", None),  # "target recommendations" - unclear scope

    # Edge cases with separators and formatting
    ("targets: playground - daily use; risks: moderate severity", "MAKE_CORRECTION", "targets"),
    ("area description: residential context, tree description: oak species", "MAKE_CORRECTION", "area_description"),
    ("update in targets the proximity; also in recommendations set removal", "MAKE_CORRECTION", "targets"),
    ("change for area description the site use and for risks the rationale", "MAKE_CORRECTION", "area_description"),
    ("modify under tree description the crown shape to pyramidal", "MAKE_CORRECTION", "tree_description"),

    # Nested/complex phrasing
    ("please note that in area description the context should reflect commercial use", "MAKE_CORRECTION",
     "area_description"),
    ("I need to update the tree description (specifically the dbh measurement) to 42 inches", "MAKE_CORRECTION",
     "tree_description"),
    ("kindly adjust the targets section, particularly the proximity field to within strike potential",
     "MAKE_CORRECTION", "targets"),
    ("the recommendations section needs updating - change pruning scope to crown reduction", "MAKE_CORRECTION",
     "recommendations"),
    ("for the risks section, please modify the severity to high and rationale to 'structural failure imminent'",
     "MAKE_CORRECTION", "risks"),

    # Units and measurements that could confuse parsing
    ("change dbh to 30 in targets: playground area", "MAKE_CORRECTION", "tree_description"),  # "30 in" vs "in targets"
    ("update height 45 ft in area description: commercial zone", "MAKE_CORRECTION", "tree_description"),
    ("set crown diameter 25 ft for recommendations: crown clean", "MAKE_CORRECTION", "tree_description"),
    ("modify 6 in targets proximity to beyond strike range", "MAKE_CORRECTION", "targets"),  # "6 in targets" - tricky
    ("adjust 12 in area description context to residential", "MAKE_CORRECTION", "area_description"),

    # =========================
    # CHALLENGING SECTION_SUMMARY CASES
    # =========================

    # Multiple sections mentioned
    ("overview of targets and recommendations sections", "SECTION_SUMMARY", "targets"),  # Which section to prioritize?
    ("summary of tree description and area description", "SECTION_SUMMARY", "tree_description"),
    ("brief recap of risks, targets, and current recommendations", "SECTION_SUMMARY", "risks"),
    ("provide summaries for both area description and tree description", "SECTION_SUMMARY", "area_description"),
    ("I need overviews of the recommendations section and risks section", "SECTION_SUMMARY", "recommendations"),

    # Ambiguous references
    ("describe the assessment details", "SECTION_SUMMARY", None),  # Could be any section
    ("summarize the environmental factors", "SECTION_SUMMARY", None),  # Unclear which section
    ("overview of site conditions", "SECTION_SUMMARY", None),  # Could be area_description or targets
    ("recap the structural analysis", "SECTION_SUMMARY", None),  # Could be tree_description or risks
    ("summary of management options", "SECTION_SUMMARY", None),  # Likely recommendations but unclear

    # Complex nested phrasing
    ("can you provide me with a comprehensive overview focusing on the tree description section details",
     "SECTION_SUMMARY", "tree_description"),
    ("I'd like a detailed summary of what's currently captured in the targets section", "SECTION_SUMMARY", "targets"),
    ("please generate a brief but thorough recap of the recommendations section content", "SECTION_SUMMARY",
     "recommendations"),
    ("give me an executive summary specifically for the area description section", "SECTION_SUMMARY",
     "area_description"),
    ("provide a high-level overview with emphasis on the risks section findings", "SECTION_SUMMARY", "risks"),

    # Sections with modifiers that might confuse parsing
    ("summary of target locations", "SECTION_SUMMARY", "targets"),  # "target locations" vs "targets"
    ("overview of risk factors", "SECTION_SUMMARY", "risks"),  # "risk factors" vs "risks"
    ("describe the tree characteristics", "SECTION_SUMMARY", "tree_description"),  # Alternative phrasing
    ("recap site description", "SECTION_SUMMARY", "area_description"),  # "site description" vs "area description"
    ("summarize management recommendations", "SECTION_SUMMARY", "recommendations"),  # Modified section name

    # =========================
    # CHALLENGING QUICK_SUMMARY CASES
    # =========================

    # Potential false positives for section summaries
    ("quick summary of tree and site conditions", "QUICK_SUMMARY", None),  # Mentions specific areas but wants overall
    ("brief overview of all assessment areas", "QUICK_SUMMARY", None),
    ("rapid status check across all sections", "QUICK_SUMMARY", None),
    ("fast summary covering targets, risks, and recommendations", "QUICK_SUMMARY", None),
    ("condensed overview of tree description and area context", "QUICK_SUMMARY", None),

    # Complex phrasing that might be misclassified
    ("I need a comprehensive but brief assessment summary", "QUICK_SUMMARY", None),
    ("can you provide an executive-level overview of the current state", "QUICK_SUMMARY", None),
    ("give me the 30-second elevator pitch on our assessment", "QUICK_SUMMARY", None),
    ("what's the bottom line summary of where we stand", "QUICK_SUMMARY", None),
    ("rapid fire overview of all current findings", "QUICK_SUMMARY", None),

    # =========================
    # CHALLENGING MAKE_REPORT_DRAFT CASES
    # =========================

    # Potential confusion with section summaries
    ("create a detailed report on tree description findings", "MAKE_REPORT_DRAFT", None),
    # Mentions section but wants full report
    ("generate a comprehensive assessment report covering all areas", "MAKE_REPORT_DRAFT", None),
    ("draft a technical report including targets and risk analysis", "MAKE_REPORT_DRAFT", None),
    ("prepare a professional report documenting tree description and recommendations", "MAKE_REPORT_DRAFT", None),
    ("build a formal assessment report with area description and risk factors", "MAKE_REPORT_DRAFT", None),

    # Complex/formal phrasing
    ("I require a professionally formatted assessment document", "MAKE_REPORT_DRAFT", None),
    ("please prepare a comprehensive technical evaluation report", "MAKE_REPORT_DRAFT", None),
    ("generate a formal documentation package for this assessment", "MAKE_REPORT_DRAFT", None),
    ("create an official report suitable for regulatory submission", "MAKE_REPORT_DRAFT", None),
    ("draft a complete assessment report with all relevant findings", "MAKE_REPORT_DRAFT", None),

    # =========================
    # EDGE CASES & BOUNDARY CONDITIONS
    # =========================

    # Empty/minimal content after scope
    ("targets:", "MAKE_CORRECTION", "targets"),  # No payload after scope
    ("update area description:", "MAKE_CORRECTION", "area_description"),
    ("in recommendations", "SECTION_SUMMARY", "recommendations"),  # Minimal text
    ("for risks:", "MAKE_CORRECTION", "risks"),

    # Multiple colons and separators
    ("targets: playground: daily use", "MAKE_CORRECTION", "targets"),  # Double colon
    ("area description: context: commercial; site: urban", "MAKE_CORRECTION", "area_description"),
    ("tree description: species: oak: red oak", "MAKE_CORRECTION", "tree_description"),

    # Potential false scope matches
    ("the area around the tree needs description", "MAKE_CORRECTION", None),  # "area...description" but not scoped
    ("target the recommendations section", "SECTION_SUMMARY", None),  # "target" + "recommendations"
    ("risk assessment in the area of concern", "MAKE_CORRECTION", None),  # "risk" + "area"
    ("describe targeting methods", "SECTION_SUMMARY", None),  # Contains "target" but different meaning

    # Capitalization variations
    ("update TARGETS proximity", "MAKE_CORRECTION", "targets"),
    ("Area Description: residential context", "MAKE_CORRECTION", "area_description"),
    ("TREE DESCRIPTION species change", "MAKE_CORRECTION", "tree_description"),
    ("modify Recommendations pruning scope", "MAKE_CORRECTION", "recommendations"),
    ("RISKS: severity level high", "MAKE_CORRECTION", "risks"),
]

# Consolidated challenging test corpus
CHALLENGING_CORPUS = CHALLENGING_TEST_CASES