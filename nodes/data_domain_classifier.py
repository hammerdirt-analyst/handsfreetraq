from __future__ import annotations
import os
from typing import List, Literal
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

DomainLabel = Literal[
    "arborist_info",
    "customer_info",
    "tree_description",
    "area_description",
    "targets",
    "risks",
    "recommendations",
]

class DomainResult(BaseModel):
    # min_items enforces “pick at least one” when LC parses the response
    domains: List[DomainLabel] = Field(default_factory=list, min_items=1)

def classify_data_domains(utterance: str) -> DomainResult:
    text = (utterance or "").strip()
    if not text:
        # leave extraction to decide; here we require something to classify
        return DomainResult(domains=["customer_info"])  # safe default for empty unlikely input

    if os.getenv("LLM_BACKEND", "openai").strip().lower() != "openai":
        raise RuntimeError("Domain classifier LLM unavailable: LLM_BACKEND != 'openai'")

    try:
        llm = ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0)
    except Exception as e:
        raise RuntimeError(f"Domain classifier init failed: {e}")

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a router for an arborist report. Given ONE user message that PROVIDES DATA, "
         "select ALL applicable domains and return ONLY a JSON object that matches the schema "
         "bound by the tool.\n\n"
         "Allowed domains: arborist_info | customer_info | tree_description | area_description | targets | risks | recommendations\n\n"
         "Rules:\n"
         "1) The speaker is the ARBORIST. First-person identifiers (e.g., 'my name is …', 'I'm …', 'my license …') belong to arborist_info.\n"
         "2) Include a domain ONLY if the user clearly provided info for it.\n"
         "3) Return JSON only."),
    ])

    structured = llm.with_structured_output(DomainResult)
    chain = prompt | structured
    try:
        result: DomainResult = chain.invoke({"utterance": text})
    except Exception as e:
        raise RuntimeError(f"Domain classifier LLM call failed: {e}")

    # final guard
    allowed = {
        "arborist_info","customer_info","tree_description",
        "area_description","targets","risks","recommendations"
    }
    result.domains = [d for d in result.domains if d in allowed]
    if not result.domains:
        # If LC/Pydantic didn’t enforce (older LC), don’t quietly pass empty.
        raise RuntimeError("Domain classifier returned no domains for a PROVIDE_DATA utterance")
    return result
