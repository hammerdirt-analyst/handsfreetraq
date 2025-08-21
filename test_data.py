# test_data.py — fixtures for coordinator + runners

from __future__ import annotations
from typing import Dict, List, Any

# ---- Default Arborist profile (fully populated; no "Not provided") ----
ARBORIST_PROFILE: Dict[str, Any] = {
    "name": "Casey Usher",
    "company": "Casey Tree Inspections",
    "phone": "123 345 9876",
    "email": "casey@email.com",
    "license": "CA-ARB-0001",
    "address": {
        "street": "1234 High Street",
        "city": "Rio Linda",
        "state": "CA",
        "postal_code": "56789",
        "country": "US",
    },
}

def arborist_updates_envelope() -> Dict[str, Any]:
    """Return a coordinator-friendly updates envelope for merging."""
    return {"updates": {"arborist_info": ARBORIST_PROFILE}}

# ---- Golden phrases for quick checks ---------------------------------
PHRASES: List[str] = [
    "my name is roger erismann",
    "customer address is 12 oak ave, san jose ca 95112",
    "dbh is 24 inches and height 60 ft",
    "give me a short summary",
    "what's left?",
    "thanks!",
]

# ---- Lightweight expectations (intent + domains only) ----------------
# Use where helpful; coordinators/runners can ignore if not supplied.
EXPECTATIONS: Dict[str, Dict[str, Any]] = {
    "my name is roger erismann": {
        "intent": "PROVIDE_DATA",
        "domains": ["customer_info"],  # first-person defaults to arborist, but our domain router may pick customer_info; adjust as you tune
    },
    "customer address is 12 oak ave, san jose ca 95112": {
        "intent": "PROVIDE_DATA",
        "domains": ["customer_info"],
    },
    "dbh is 24 inches and height 60 ft": {
        "intent": "PROVIDE_DATA",
        "domains": ["tree_description"],
    },
    "give me a short summary": {
        "intent": "REQUEST_SUMMARY",
    },
    "what's left?": {
        "intent": "WHAT_IS_LEFT",
    },
    "thanks!": {
        "intent": "SMALL_TALK",
    },
}
