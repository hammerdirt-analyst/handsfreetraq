#!/usr/bin/env python3
"""
Project: Arborist Agent
File: report_agent.py
Author: roger erismann (cleaned for PEP 8)

ReportAgent
-----------
- Produces the initial draft report (all sections) from state + provenance.
- Subsequent edit flows will be added later (Prompt B). For now, only Prompt A.

Behavior
- Inputs: full ReportState (including 'Not provided'), full provenance
  (deduped for scalar paths).
- Output: Markdown with H2 subtitles per section, fixed order:
    ## Area Description
    ## Tree Description
    ## Targets
    ## Risks
    ## Recommendations
  Each paragraph is prefixed with a stable ID: [<section_id>-pN].
  At the end of each section (first draft only), add an "Editor Comment"
  line summarizing omitted / not-provided fields.

- Deterministic call pattern via langchain_openai.ChatOpenAI.invoke(
  [SystemMessage, HumanMessage]).
- Token usage returned when available: {"in": <prompt_tokens>, "out": <completion_tokens>}.

Public API (unchanged)
- class ReportAgent:
    - __init__(model: str | None = None, client: Any = None)
    - has_draft() -> bool
    - run(mode="draft", state, provenance, user_text="", temperature=0.35, style=None) -> dict
    - _run_initial_draft(state, provenance, temperature, style) -> dict
    - _system_prompt_initial(style) -> str
    - _user_payload_initial(state, provenance, style) -> str
    - _extract_token_usage(ai_message) -> (int, int)
    - _postprocess_and_store(markdown_text) -> None
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Literal, Optional, Tuple, TypedDict

import dotenv
from langchain_core.messages import HumanMessage, SystemMessage

from arborist_report.report_state import NOT_PROVIDED, ProvenanceEvent, ReportState
from arborist_report.models import chatllm_invoke

dotenv.load_dotenv()


# ------------------------------ Constants -------------------------------------

HEADINGS_ORDER: List[str] = [
    "Area Description",
    "Tree Description",
    "Targets",
    "Risks",
    "Recommendations",
]

SECTION_ID_MAP: Dict[str, str] = {
    "Area Description": "area_description",
    "Tree Description": "tree_description",
    "Targets": "targets",
    "Risks": "risks",
    "Recommendations": "recommendations",
}


# ------------------------------ Types -----------------------------------------

class DraftParagraph(TypedDict):
    id: str
    text: str


class DraftSection(TypedDict, total=False):
    title: str
    paragraphs: List[DraftParagraph]


DraftReport = Dict[str, DraftSection]


# ---------------------------- Module Helpers ----------------------------------


def _pydantic_dump(obj: Any) -> Any:
    """Return a plain-JSONable structure for pydantic models or dicts."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(exclude_none=False)
    return obj


def _strip_trailing_spaces(markdown_text: str) -> str:
    """Collapse trailing spaces at line ends for cleaner diffs."""
    return re.sub(r"[ \t]+(\n|$)", r"\1", markdown_text)


def _parse_markdown_index(markdown_text: str) -> DraftReport:
    """
    Build a simple index of sections and paragraphs from the draft markdown.
    - Detect H2 headings.
    - Collect paragraphs, honoring [section_id-pN] markers when present.
    """
    index: DraftReport = {}
    current_section: Optional[str] = None

    # Split on blank lines; robust to varying whitespace.
    for block in re.split(r"\n\s*\n", markdown_text.strip()):
        block_stripped = block.strip()

        # Heading?
        m_h2 = re.match(r"^##\s+([A-Za-z_ ]+)\s*$", block_stripped)
        if m_h2:
            name = m_h2.group(1).strip()
            sec_id = name.lower().replace(" ", "_")
            current_section = sec_id
            index.setdefault(current_section, {"title": name, "paragraphs": []})
            continue

        # Paragraph under a section.
        if current_section:
            m_id = re.match(
                r"^\s*\[([a-z_]+-p\d+)\]\s*(.+)$", block_stripped, flags=re.DOTALL
            )
            if m_id:
                pid, ptext = m_id.group(1), m_id.group(2).strip()
                index[current_section]["paragraphs"].append({"id": pid, "text": ptext})
            else:
                # If no explicit ID, synthesize a stable one.
                idx = len(index[current_section]["paragraphs"]) + 1
                index[current_section]["paragraphs"].append(
                    {"id": f"{current_section}-p{idx}", "text": block_stripped}
                )

    return index


# ------------------------------- Agent ----------------------------------------


class ReportAgent:
    """
    Produces the initial full Markdown draft from ReportState + provenance.

    Notes:
      - Only 'draft' mode is supported at the moment (Prompt A).
      - The agent stores the raw draft and a parsed index for future edit flows.
    """

    def __init__(self, model: Optional[str] = None, client: Any = None) -> None:
        """
        Args:
            model: OpenAI model name (used if client is None). Defaults to
                   $OPENAI_MODEL or 'gpt-4o-mini'.
            client: Optional injected Chat client with .invoke(messages).
        """
        self._model_name: str = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self._client: Any = client  # created lazily if None
        self._draft_text: Optional[str] = None
        self._draft_index: Optional[DraftReport] = None

    # ------------------------------ Public API --------------------------------

    def has_draft(self) -> bool:
        """Return True if a draft was previously generated and stored."""
        return self._draft_text is not None

    def run(
        self,
        *,
        mode: Literal["draft"] = "draft",
        state: ReportState,
        provenance: List[ProvenanceEvent],
        user_text: str = "",
        temperature: float = 0.35,
        style: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        mode='draft' → produce an initial full draft from state + provenance.

        Returns:
            dict: {"draft_text": str, "tokens": {"in": int, "out": int}, "model": str}
        """
        if mode != "draft":
            raise ValueError(
                "ReportAgent currently supports mode='draft' only (Prompt A)."
            )

        return self._run_initial_draft(
            state=state, provenance=provenance, temperature=temperature, style=style or {}
        )

    # ----------------------- Prompt A (initial draft) -------------------------

    def _run_initial_draft(
        self,
        *,
        state: ReportState,
        provenance: List[ProvenanceEvent],
        temperature: float,
        style: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Invoke the LLM to generate the first draft and store it."""
        system = self._system_prompt_initial(style)
        user = self._user_payload_initial(state, provenance, style)

        # Prepare messages (two shapes: LC-objects for injected client; dicts for shared helper)
        lc_messages = [SystemMessage(content=system), HumanMessage(content=user)]
        dict_messages = [{"role": "system", "content": system},
                         {"role": "user", "content": user}]

        if self._client is not None:
            # Use the injected client path (tests, fakes, or a prebuilt ChatOpenAI)
            ai_msg = self._client.invoke(lc_messages)
            text = (getattr(ai_msg, "content", "") or "").strip()
            tok_in, tok_out = self._extract_token_usage(ai_msg)
            tokens = {"in": tok_in, "out": tok_out}
            model = self._model_name
        else:
            # Standard path: shared helper (unifies token/model capture)
            llm_out = chatllm_invoke(
                messages=dict_messages,
                temperature=temperature,
                max_tokens=None,  # keep None unless you want to cap
                response_format=None,  # draft is markdown text
                model_name=self._model_name,
            )
            text = (llm_out["text"] or "").strip()
            tokens = llm_out["tokens"]  # {"in": int, "out": int}
            model = llm_out["model"]

        text = _strip_trailing_spaces(text)

        # Store draft internally for future edit mode (Prompt B).
        self._postprocess_and_store(text)

        return {
            "draft_text": text,
            "tokens": tokens,
            "model": model,
        }

    @staticmethod
    def _system_prompt_initial(style: Dict[str, Any]) -> str:
        """
        Drafting rules for the first pass (Prompt A).
        """
        reading = str(style.get("reading_level", "general"))
        length = str(style.get("length", "medium"))
        return (
            "You are an arborist reporting assistant.\n"
            "TASK: Write a complete initial draft of the arborist report from the provided JSON.\n"
            "RULES:\n"
            "1) Use ONLY facts present in the JSON state/provenance. Do NOT invent facts.\n"
            "2) Ignore fields with the exact string 'Not provided' and empty arrays in the body text.\n"
            "3) Output Markdown with exactly these H2s, in this order:\n"
            f"   ## {HEADINGS_ORDER[0]}\n"
            f"   ## {HEADINGS_ORDER[1]}\n"
            f"   ## {HEADINGS_ORDER[2]}\n"
            f"   ## {HEADINGS_ORDER[3]}\n"
            f"   ## {HEADINGS_ORDER[4]}\n"
            "4) Under each H2, write 1–3 coherent paragraphs. Keep sentences concise.\n"
            "5) Prefix each paragraph with an ID: [<section_id>-pN], e.g., [tree_description-p1].\n"
            "6) Use units present in the JSON verbatim (do not convert or add estimates).\n"
            "7) After the body paragraphs in each section, add one final paragraph titled "
            "'Editor Comment:' that briefly lists any fields in that section that were "
            "omitted or marked 'Not provided'. If nothing is missing, write "
            "'Editor Comment: All primary fields provided.'\n"
            "8) Do not generalize beyond what’s in JSON; avoid filler phrases.\n"
            f"9) Tone: neutral, professional. Reading level: {reading}. "
            f"Target overall length: {length}.\n"
            "10) Output only Markdown (no JSON, no YAML).\n"
        )

    @staticmethod
    def _user_payload_initial(
        state: ReportState, provenance: List[ProvenanceEvent], style: Dict[str, Any]
    ) -> str:
        """
        Single JSON blob the model will rely on for factual content. We include the exact
        section snapshots and the full (deduped) provenance so the model can favor confirmed
        values.
        """
        sections = {
            "area_description": _pydantic_dump(getattr(state, "area_description")),
            "tree_description": _pydantic_dump(getattr(state, "tree_description")),
            "targets": _pydantic_dump(getattr(state, "targets")),
            "risks": _pydantic_dump(getattr(state, "risks")),
            "recommendations": _pydantic_dump(getattr(state, "recommendations")),
        }

        prov_rows: List[Dict[str, Any]] = []
        for p in provenance or []:
            prov_rows.append(_pydantic_dump(p))

        payload = {
            "version": "report_initial_v1",
            "style": {
                "reading_level": style.get("reading_level", "general"),
                "length": style.get("length", "medium"),
            },
            "sections": sections,
            "provenance": prov_rows,
            "not_provided_token": NOT_PROVIDED,
            "output_contract": {
                "format": "markdown",
                "headings": HEADINGS_ORDER,
                "paragraph_ids": "[<section_id>-pN]",
                "section_id_map": SECTION_ID_MAP,
                "editor_comment": (
                    "At end of each section, add 'Editor Comment:' paragraph listing omitted fields."
                ),
            },
        }
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _extract_token_usage(ai_message: Any) -> Tuple[int, int]:
        """
        Extract token usage from a LangChain message if available.
        Supports both response_metadata.token_usage and usage_metadata conventions.
        """
        try:
            meta = getattr(ai_message, "response_metadata", {}) or {}
            usage = meta.get("token_usage") or {}
            if usage:
                return (
                    int(usage.get("prompt_tokens", 0) or 0),
                    int(usage.get("completion_tokens", 0) or 0),
                )
        except Exception:
            pass
        try:
            usage2 = getattr(ai_message, "usage_metadata", {}) or {}
            if usage2:
                return (
                    int(usage2.get("input_tokens", 0) or 0),
                    int(usage2.get("output_tokens", 0) or 0),
                )
        except Exception:
            pass
        return 0, 0

    def _postprocess_and_store(self, markdown_text: str) -> None:
        """
        Persist the raw draft and build a simple index of paragraph IDs per section.
        (We keep it light; detailed edit coordination comes with Prompt B.)
        """
        self._draft_text = markdown_text
        self._draft_index = _parse_markdown_index(markdown_text)
