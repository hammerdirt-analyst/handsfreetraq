# quick_ping_corrections_agent.py
import os, json
from report_state import ReportState
from corrections_agent import CorrectionsAgent

# assume dotenv has been loaded via module import
os.environ.setdefault("OPENAI_MODEL", "gpt-4o-mini")

state = ReportState()
agent = CorrectionsAgent()

# Example: change DBH + add a trunk note
user_text = "Set the DBH to 30 in and add 'old pruning wounds present' to trunk notes."
res = agent.run(section="tree_description", text=user_text, state=state, policy="last_write", temperature=0.0)
print(json.dumps(res, ensure_ascii=False, indent=2))

# If you want to actually apply the updates to state:
# from datetime import datetime
# now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
# new_state = state.model_merge_updates(
#     res["updates"],
#     policy=res["policy"],
#     turn_id=now,
#     timestamp=now,
#     domain=res["section"],
#     extractor="CorrectionsAgent",
#     model_name=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
#     segment_text=user_text,
# )
# print(json.dumps(new_state.model_dump(exclude_none=False), ensure_ascii=False, indent=2))
