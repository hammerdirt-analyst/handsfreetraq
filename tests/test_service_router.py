# test_service_router.py

from typing import Tuple, Optional, Any
from service_router import classify_service
import tests.TEST_CORPUS as TEST_CORPUS


def _adapt_output(raw: Any) -> Tuple[str, Optional[str]]:
    """
    Accept either:
      - ('SERVICE', 'section'|None)
      - {'service': 'SERVICE', 'section': 'section'|None, ...}
    and return (service, section)
    """
    if isinstance(raw, tuple) and len(raw) == 2:
        return raw[0], raw[1]
    if isinstance(raw, dict):
        return raw.get("service"), raw.get("section")
    # Fallback: treat anything else as NONE
    return "NONE", None

def run():
    cases = TEST_CORPUS.TEST_CORPUS
    total = len(cases)
    passed = 0
    failed_cases = []

    for idx, (text, exp_service, exp_section) in enumerate(cases, start=1):
        raw = classify_service(text)  # deterministic router (or your coordinator payload)
        got_service, got_section = _adapt_output(raw)
        if got_service == exp_service and got_section == exp_section:
            passed += 1
        else:
            failed_cases.append((idx, text, (exp_service, exp_section), (got_service, got_section)))

    print(f"Total: {total}  Passed: {passed}  Failed: {total - passed}")
    if failed_cases:
        print("----")
        for idx, text, expected, got in failed_cases:
            print(f"#{idx}:")
            print(f"text:       {text}")
            print(f"expected:   {expected}")
            print(f"got:        {got}")
            print("----")

if __name__ == "__main__":
    run()
