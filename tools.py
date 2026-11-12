"""Tools for SevaAgent: scheme lookup, web search, eligibility checker.

Everything here works offline except web_search(), which uses DuckDuckGo
(ddgs package, with an HTML fallback through requests).
"""

import json
import os
import re
from urllib.parse import quote_plus

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemes.json")

# Common words that carry no meaning for scheme matching (English + Hindi).
STOPWORDS = {
    "the", "for", "and", "are", "you", "your", "can", "what", "which",
    "with", "there", "here", "her", "his", "our", "get", "tell", "please",
    "about", "from", "that", "this", "have", "has", "will", "would",
    "kya", "hai", "ka", "ki", "ke", "ko", "se", "mein", "main", "mujhe",
    "mere", "liye", "hoga", "hogi", "kaun", "kaisa", "kaise", "aur",
}

# Occupation labels used by the UI profile form.
OCCUPATIONS = [
    ("farmer", "Farmer / खेती"),
    ("artisan", "Artisan / craftsperson (carpenter, tailor, potter, etc.)"),
    ("student", "Student / विद्यार्थी"),
    ("business_owner", "Small business owner / shopkeeper"),
    ("self_employed", "Self-employed (other)"),
    ("salaried", "Salaried / private job"),
    ("govt_employee", "Government employee"),
    ("daily_wage", "Daily-wage / casual worker"),
    ("homemaker", "Homemaker"),
    ("retired", "Retired"),
    ("other", "Other / not sure"),
]

INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim",
    "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal", "Delhi", "Jammu and Kashmir", "Ladakh",
    "Puducherry", "Chandigarh", "Andaman and Nicobar Islands",
]


def load_schemes():
    """Load the curated schemes dataset."""
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["schemes"]


def search_schemes(query, schemes=None, top_n=3):
    """Keyword search over the curated dataset.

    Scores matches on name, keywords, description and category.
    Returns a list of (scheme, score) sorted by score, best first.
    """
    schemes = schemes or load_schemes()
    words = [w for w in re.findall(r"[a-zA-Z\u0900-\u097F]+", query.lower())
             if len(w) > 2 and w not in STOPWORDS]
    if not words:
        return []
    scored = []
    for s in schemes:
        hay_name = (s["name"] + " " + s.get("name_hi", "")).lower()
        hay_keys = " ".join(s.get("keywords", [])).lower()
        hay_desc = (s["description"] + " " + s.get("benefit", "")).lower()
        score = 0
        for w in words:
            if w in hay_name:
                score += 5
            if w in hay_keys:
                score += 4
            if w in hay_desc:
                score += 1
        if score > 0:
            scored.append((s, score))
    scored.sort(key=lambda t: -t[1])
    return scored[:top_n]


def web_search(query, max_results=3):
    """Search the web with DuckDuckGo and return short results.

    Tries the ddgs package first; falls back to scraping the DuckDuckGo
    HTML endpoint with requests. Returns a list of dicts
    {title, url, snippet}. Returns [] on any failure (never raises).
    """
    try:
        from ddgs import DDGS

        out = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                out.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
        return out
    except Exception:
        pass
    # Fallback: DuckDuckGo HTML endpoint, parsed with regex (no bs4 needed).
    try:
        import requests

        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (SevaAgent demo)"},
            timeout=15,
        )
        out = []
        for m in re.finditer(
            r'result__a[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?result__snippet[^>]*>(.*?)</a>',
            resp.text, re.S,
        ):
            url, title, snippet = m.groups()
            out.append({
                "title": re.sub(r"<[^>]+>", "", title).strip(),
                "url": url,
                "snippet": re.sub(r"<[^>]+>", "", snippet).strip(),
            })
            if len(out) >= max_results:
                break
        return out
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Eligibility checker
# ---------------------------------------------------------------------------

def empty_profile():
    return {
        "age": None,               # int, applicant age in years
        "annual_income": None,     # int, family income per year in INR
        "state": "",
        "category": "any",         # General / SC / ST / OBC / Minority / any
        "gender": "any",           # female / male / any
        "occupation": "other",
        "is_farmer": False,        # owns / farms land
        "has_girl_child": False,   # girl child below 10 in the family
        "is_student": False,
        "is_artisan": False,       # works in one of the 18 Vishwakarma trades
        "own_house": False,        # owns a house with a usable roof
        "has_bank_account": False,
        "area": "",                # rural / urban / ""
        "secc_listed": None,       # True / False / None (don't know)
        "has_business": False,     # runs a small non-farm business
    }


def _fmt_inr(n):
    if n >= 100000:
        return f"₹{n / 100000:g} lakh"
    return f"₹{n:,}"


def check_eligibility(profile, schemes=None):
    """Match a profile against every scheme.

    Returns a list of dicts:
      {scheme, status, reasons}
    status: 'eligible' | 'likely' | 'check' | 'not_eligible'
      eligible    — every checkable rule passes
      likely      — passes the rules we can check; one or two things
                    (e.g. SECC listing) still need verification
      check       — cannot decide from the profile; the scheme may apply
      not_eligible — fails a hard rule (age, income, gender, category,
                    occupation or a required fact)
    """
    schemes = schemes or load_schemes()
    results = []
    for s in schemes:
        e = s["eligibility"]
        reasons = []
        status = "eligible"

        def fail(msg):
            nonlocal status
            status = "not_eligible"
            reasons.append(("no", msg))

        def warn(msg):
            nonlocal status
            if status == "eligible":
                status = "likely"
            reasons.append(("check", msg))

        def ok(msg):
            reasons.append(("yes", msg))

        # --- age ---
        age = profile.get("age")
        if e.get("age_applies_to") == "girl_child":
            if profile.get("has_girl_child"):
                ok("Girl child below 10 years in the family")
            else:
                fail("Needs a girl child below 10 years in the family")
        else:
            if age is not None:
                if e.get("min_age") is not None and age < e["min_age"]:
                    fail(f"Minimum age is {e['min_age']} years (you are {age})")
                elif e.get("max_age") is not None and age > e["max_age"]:
                    fail(f"Maximum age is {e['max_age']} years (you are {age})")
                elif e.get("min_age") is not None or e.get("max_age") is not None:
                    ok(f"Age {age} is within the age limit")
            elif e.get("min_age") is not None or e.get("max_age") is not None:
                if e.get("min_age") == 70:
                    warn("Needs age 70 or above — tell us your age to confirm")
                else:
                    warn("Age not given — age limit could not be checked")

        # --- income ---
        income = profile.get("annual_income")
        cap = e.get("max_family_income_inr")
        if cap is not None:
            if income is not None:
                if income > cap:
                    fail(f"Family income must be up to {_fmt_inr(cap)} (yours: {_fmt_inr(income)})")
                else:
                    ok(f"Family income {_fmt_inr(income)} is within the limit of {_fmt_inr(cap)}")
            else:
                warn(f"Income limit is {_fmt_inr(cap)} per year — tell us your income to confirm")

        # --- category ---
        cats = e.get("categories") or ["any"]
        cat = (profile.get("category") or "any").strip()
        if "any" not in cats:
            if cat == "any":
                warn(f"Meant for {', '.join(cats)} applicants — tell us your category to confirm")
            elif cat in cats:
                ok(f"Category {cat} is covered")
            else:
                fail(f"Meant for {', '.join(cats)} applicants")

        # --- gender ---
        if e.get("gender") == "female" and profile.get("gender") == "male":
            fail("This scheme is only for women / girl children")

        # --- occupation ---
        occs = e.get("occupations") or ["any"]
        occ = profile.get("occupation") or "other"
        if "any" not in occs:
            if occ in occs:
                ok(f"Occupation ({occ}) matches")
            elif occ in ("other",):
                warn(f"Meant for {', '.join(occs)} — tell us your work to confirm")
            else:
                fail(f"Meant for {', '.join(occs)}")

        # --- required facts ---
        for req in e.get("requires", []):
            if req == "secc_listed":
                if profile.get("secc_listed") is True:
                    ok("Family is listed in SECC 2011")
                elif profile.get("secc_listed") is False:
                    fail("Family is not in the SECC 2011 list")
                else:
                    warn("Depends on the SECC 2011 list — check your name on the official portal")
            elif req == "senior_70plus":
                if age is not None and age >= 70:
                    ok("Age 70 or above")
                elif age is not None:
                    fail("Needs age 70 or above")
            elif req == "landholding":
                if profile.get("is_farmer"):
                    ok("Landholding farmer family")
                else:
                    fail("Needs a landholding farmer family")
            elif req == "girl_child":
                pass  # handled under age
            elif req == "student":
                if profile.get("is_student"):
                    ok("Student")
                else:
                    fail("Only for students")
            elif req == "artisan_trade":
                if profile.get("is_artisan"):
                    ok("Artisan in a covered trade")
                else:
                    fail("Only for artisans in the 18 listed traditional trades")
            elif req == "own_house_roof":
                if profile.get("own_house"):
                    ok("Own house with a roof")
                else:
                    fail("Needs your own house with a roof to install solar")
            elif req == "bank_account":
                if profile.get("has_bank_account"):
                    ok("Has a bank / post office account")
                else:
                    warn("Needs a savings bank or post office account")
            elif req == "rural":
                if profile.get("area") == "rural":
                    ok("Rural area")
                elif profile.get("area") == "urban":
                    fail("Only for rural areas")
            elif req == "urban":
                if profile.get("area") == "urban":
                    ok("Urban area")
                elif profile.get("area") == "rural":
                    fail("Only for urban areas")
            elif req == "no_pucca_house":
                warn("You must not own a pucca house anywhere in India")
            elif req == "business":
                if profile.get("has_business"):
                    ok("Runs a small business")
                else:
                    fail("Only for small business owners")

        if status == "eligible" and not reasons:
            # No rule to check at all (e.g. Jan Dhan: open to everyone).
            reasons.append(("yes", "Open to all — no special conditions"))
        if status == "likely" and all(r[0] == "yes" for r in reasons):
            status = "eligible"

        results.append({"scheme": s, "status": status, "reasons": reasons})

    order = {"eligible": 0, "likely": 1, "check": 2, "not_eligible": 3}
    results.sort(key=lambda r: order[r["status"]])
    return results


def profile_summary(profile):
    """One-line summary of a profile, for display."""
    bits = []
    if profile.get("age") is not None:
        bits.append(f"age {profile['age']}")
    if profile.get("annual_income") is not None:
        bits.append(f"income {_fmt_inr(profile['annual_income'])}")
    if profile.get("state"):
        bits.append(profile["state"])
    if profile.get("category") not in (None, "", "any"):
        bits.append(f"category {profile['category']}")
    if profile.get("gender") not in (None, "", "any"):
        bits.append(profile["gender"])
    occ = profile.get("occupation")
    if occ not in (None, "", "other"):
        bits.append(occ.replace("_", " "))
    return ", ".join(bits) if bits else "no details given"
