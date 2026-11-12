import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Force demo mode for the smoke test (no LLM key needed).
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("HF_TOKEN", None)

from agent import answer
from tools import check_eligibility, empty_profile, load_schemes

FAILURES = []


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL"), "-", name, detail)
    if not cond:
        FAILURES.append(name)


def main():
    schemes = load_schemes()
    check("dataset loads 13 schemes", len(schemes) == 13, f"(got {len(schemes)})")

    # Q1 — senior citizen health cover
    reply, trace = answer("I am 72 years old. Which health scheme can I get?")
    check("Q1 mentions Vaya Vandana / PM-JAY", "Vaya Vandana" in reply or "PM-JAY" in reply)
    check("Q1 uses eligibility checker", "eligibility_checker" in trace["tools"])
    print("--- Q1 reply (first 500 chars) ---")
    print(reply[:500])

    # Q2 — girl child savings
    reply, _ = answer("My daughter is 5 years old, is there a savings scheme for her?")
    check("Q2 mentions Sukanya Samriddhi", "Sukanya" in reply)
    print("--- Q2 reply (first 300 chars) ---")
    print(reply[:300])

    # Q3 — farmer help
    reply, _ = answer("I am a farmer with 2 acres of land. What help can I get?")
    check("Q3 mentions PM-KISAN", "PM-KISAN" in reply)
    check("Q3 mentions Fasal Bima", "Fasal Bima" in reply)

    # Q4 — eligibility with a full profile
    profile = empty_profile()
    profile.update(age=30, annual_income=200000, category="OBC",
                   is_farmer=True, occupation="farmer", area="rural",
                   has_bank_account=True)
    results = check_eligibility(profile)
    eligible = [r["scheme"]["id"] for r in results if r["status"] in ("eligible", "likely")]
    check("Q4 farmer profile: PM-KISAN eligible/likely", "pm-kisan" in eligible, f"(got {eligible})")
    check("Q4 farmer profile: PMJDY eligible/likely", "pmjdy" in eligible)
    check("Q4 farmer profile: Vaya Vandana NOT eligible (age 30)",
          all(r["status"] == "not_eligible" for r in results if r["scheme"]["id"] == "vaya-vandana"))
    check("Q4 farmer profile: Sukanya NOT eligible (no girl child)",
          all(r["status"] == "not_eligible" for r in results if r["scheme"]["id"] == "sukanya"))

    # Q5 — Hindi query
    reply, _ = answer("मुझे अपने छोटे व्यवसाय के लिए लोन चाहिए। कौन सी योजना है?")
    check("Q5 Hindi query mentions Mudra", "Mudra" in reply)

    # Q6 — unknown topic falls back gracefully (no crash, honest answer)
    reply, trace = answer("What is the weather in Delhi tomorrow?")
    check("Q6 off-topic query answers without crashing", len(reply) > 50)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURES: {FAILURES}")
        sys.exit(1)
    print("ALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
