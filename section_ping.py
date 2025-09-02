# quick_ping_section_agent.py
import os, json
from report_state import ReportState
from section_report_agent import SectionReportAgent
from report_context import _build_context_from_testdata
# import dotenv
# dotenv.load_dotenv()


state = ReportState(context=_build_context_from_testdata())
state.tree_description.type_common = "London plane"
state.tree_description.dbh_in = "24"
state.tree_description.height_ft = "60"
state.tree_description.narratives.append("Moderate dieback observed in upper canopy.")

agent = SectionReportAgent()
res = agent.run(section="tree_description", state=state, mode="prose", temperature=0.3, include_payload=True)
print(json.dumps(res, ensure_ascii=False, indent=2))
