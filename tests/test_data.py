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


# ============== NEW: explicit customer profile (test default) ==============
# You can fill these with real test data later; using "Not provided" is fine
# for now and keeps "what's left" meaningful.
CUSTOMER_PROFILE: Dict[str, Any] = {
    "name": "Not provided",
    "company": "Not provided",
    "phone": "Not provided",
    "email": "Not provided",
    "address": {
        "street": "Not provided",
        "city": "Not provided",
        "state": "Not provided",
        "postal_code": "Not provided",
        "country": "Not provided",
    },
}

def customer_updates_envelope() -> Dict[str, Any]:
    """Updates envelope for the customer section."""
    return {"updates": {"customer_info": CUSTOMER_PROFILE}}


# ============== NEW: tree location (lat/lon) bootstrap =====================
DEFAULT_LOCATION = {
    "latitude": 38.6732,
    "longitude": -121.4520,
}

def location_updates_envelope() -> Dict[str, Any]:
    """Updates envelope for tree_location."""
    return {"updates": {"tree_location": DEFAULT_LOCATION}}


# Handy: combined bootstrap (arborist + customer + location)
def bootstrap_updates_envelope() -> Dict[str, Any]:
    env: Dict[str, Any] = {"updates": {}}
    env["updates"]["arborist_info"] = ARBORIST_PROFILE
    env["updates"]["customer_info"] = CUSTOMER_PROFILE
    env["updates"]["tree_location"] = DEFAULT_LOCATION
    return env


# ---- Golden phrases for quick checks ---------------------------------
PHRASES: List[str] = [
    # # --- Tree Description (health, defects, roots, observations) ---
    # "the tree canopy width is approximately 35 feet",
    # "the crown shape is broadly spreading with dense foliage",
    # "the trunk has several small cracks near the base",
    # "the tree height is about 40 ft with a dbh of 15 inches",
    # "general observations indicate sparse foliage on the upper branches",
    # "the roots extend into the neighbor’s driveway",
    # "observed defects include bark peeling on the south side",
    # "the scientific name of the tree is Quercus agrifolia",
    # "the common type of the tree is coast live oak",
    # "the tree shows overall good vigor with no visible pest damage",
    #
    # # --- Area Description ---
    # "the site use is residential backyard with moderate foot traffic",
    # "the area context is a school campus with adjacent playground",
    # "foot traffic level is low due to restricted access",
    # "the surrounding context includes parking lots and sidewalks",
    # "the site use is a city park with frequent visitors",
    #
    # # --- Risks ---
    # "risk identified is broken limb over the street with high severity",
    # "falling cones are likely to cause injuries to pedestrians",
    # "the likelihood of branch failure is moderate with low severity",
    # "there is risk of root uplift damaging nearby pavement",
    # "observed risk includes hanging deadwood above the walkway",

    # --- Recommendations (pruning/removal/maintenance) ---
    "recommend pruning to remove dead branches over the roof",
    "scope of pruning should include crown thinning for better airflow",
    "limitations include restricted access for large equipment",
    "continued maintenance should involve annual inspections",
    "recommend removal of the declining elm near the fence",
    "notes indicate pruning should be completed before storm season",
    "pruning narrative suggests selective thinning to reduce weight",
    "removal scope is limited to the east side due to property lines",
    "maintenance notes include mulching and irrigation adjustments",
    "recommend pruning to elevate the canopy above the roadway",
    # "give me a short summary of the report so far",
    # "draft the full arborist report",
    # "what fields are still missing from the report",
    # "can you correct the tree height to 55 feet",
    # "please update the report with the correct customer email",
    # "tell me more about arboriculture best practices",
    # "can you explain how risk severity is determined",
    # "what did you capture for DBH",
    # "summarize everything we have entered so far",
    # "generate a report draft with current data",

]

# ---- Lightweight expectations (intent + domains only) ----------------
# ---- Lightweight expectations (intent + domains only) ----------------
# Coordinator policy: arborist_info / customer_info / location are context-only.
# They are NOT editable via the coordinator and will be deflected.
EXPECTATIONS: Dict[str, Dict[str, Any]] = {
    # # --- Tree Description (health, defects, roots, observations) ---
    # "the tree canopy width is approximately 35 feet": {"intent": "PROVIDE_STATEMENT", "domains": ["tree_description"]},
    # "the crown shape is broadly spreading with dense foliage": {"intent": "PROVIDE_STATEMENT", "domains": ["tree_description"]},
    # "the trunk has several small cracks near the base": {"intent": "PROVIDE_STATEMENT", "domains": ["tree_description"]},
    # "the tree height is about 40 ft with a dbh of 15 inches": {"intent": "PROVIDE_STATEMENT", "domains": ["tree_description"]},
    # "general observations indicate sparse foliage on the upper branches": {"intent": "PROVIDE_STATEMENT", "domains": ["tree_description"]},
    # "the roots extend into the neighbor’s driveway": {"intent": "PROVIDE_STATEMENT", "domains": ["tree_description"]},
    # "observed defects include bark peeling on the south side": {"intent": "PROVIDE_STATEMENT", "domains": ["tree_description"]},
    # "the scientific name of the tree is Quercus agrifolia": {"intent": "PROVIDE_STATEMENT", "domains": ["tree_description"]},
    # "the common type of the tree is coast live oak": {"intent": "PROVIDE_STATEMENT", "domains": ["tree_description"]},
    # "the tree shows overall good vigor with no visible pest damage": {"intent": "PROVIDE_STATEMENT", "domains": ["tree_description"]},
    #
    # # --- Area Description ---
    # "the site use is residential backyard with moderate foot traffic": {"intent": "PROVIDE_STATEMENT", "domains": ["area_description"]},
    # "the area context is a school campus with adjacent playground": {"intent": "PROVIDE_STATEMENT", "domains": ["area_description"]},
    # "foot traffic level is low due to restricted access": {"intent": "PROVIDE_STATEMENT", "domains": ["area_description"]},
    # "the surrounding context includes parking lots and sidewalks": {"intent": "PROVIDE_STATEMENT", "domains": ["area_description"]},
    # "the site use is a city park with frequent visitors": {"intent": "PROVIDE_STATEMENT", "domains": ["area_description"]},
    # # --- Risks ---
    # "risk identified is broken limb over the street with high severity": {"intent": "PROVIDE_STATEMENT", "domains": ["risks"]},
    # "falling cones are likely to cause injuries to pedestrians": {"intent": "PROVIDE_STATEMENT", "domains": ["risks"]},
    # "the likelihood of branch failure is moderate with low severity": {"intent": "PROVIDE_STATEMENT", "domains": ["risks"]},
    # "there is risk of root uplift damaging nearby pavement": {"intent": "PROVIDE_STATEMENT", "domains": ["risks"]},
    # "observed risk includes hanging deadwood above the walkway": {"intent": "PROVIDE_STATEMENT", "domains": ["risks"]},

    # --- Recommendations (pruning/removal/maintenance) ---
    "recommend pruning to remove dead branches over the roof": {"intent": "PROVIDE_STATEMENT", "domains": ["recommendations"]},
    "scope of pruning should include crown thinning for better airflow": {"intent": "PROVIDE_STATEMENT", "domains": ["recommendations"]},
    "limitations include restricted access for large equipment": {"intent": "PROVIDE_STATEMENT", "domains": ["recommendations"]},
    "continued maintenance should involve annual inspections": {"intent": "PROVIDE_STATEMENT", "domains": ["recommendations"]},
    "recommend removal of the declining elm near the fence": {"intent": "PROVIDE_STATEMENT", "domains": ["recommendations"]},
    "notes indicate pruning should be completed before storm season": {"intent": "PROVIDE_STATEMENT", "domains": ["recommendations"]},
    "pruning narrative suggests selective thinning to reduce weight": {"intent": "PROVIDE_STATEMENT", "domains": ["recommendations"]},
    "removal scope is limited to the east side due to property lines": {"intent": "PROVIDE_STATEMENT", "domains": ["recommendations"]},
    "maintenance notes include mulching and irrigation adjustments": {"intent": "PROVIDE_STATEMENT", "domains": ["recommendations"]},
    "recommend pruning to elevate the canopy above the roadway": {"intent": "PROVIDE_STATEMENT", "domains": ["recommendations"]},
    # "give me a short summary of the report so far": {"intent": "REQUEST_SERVICE"},
    # "draft the full arborist report": {"intent": "REQUEST_SERVICE"},
    # "what fields are still missing from the report": {"intent": "REQUEST_SERVICE"},
    # "can you correct the tree height to 55 feet": {"intent": "REQUEST_SERVICE"},
    # "please update the report with the correct customer email": {"intent": "REQUEST_SERVICE"},
    # "tell me more about arboriculture best practices": {"intent": "REQUEST_SERVICE"},
    # "can you explain how risk severity is determined": {"intent": "REQUEST_SERVICE"},
    # "what did you capture for DBH": {"intent": "REQUEST_SERVICE"},
    # "summarize everything we have entered so far": {"intent": "REQUEST_SERVICE"},
    # "generate a report draft with current data": {"intent": "REQUEST_SERVICE"},
}
