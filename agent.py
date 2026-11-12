"""SevaAgent — the agent itself.

Flow for every user message:
  1. Detect language (English / Hindi) and pull any profile hints
     (age, income, state) out of the message text.
  2. Tool 1 — search the curated schemes dataset.
  3. Tool 2 — run the eligibility checker when the message carries
     profile details or asks about eligibility.
  4. Tool 3 — web search when the user asks for the latest news, or
     when nothing in the dataset matches.
  5. Answer: with an LLM key, the LLM writes the reply from the tool
     results; without a key, a template answer is built from the same
     tool results (demo mode — the app still works end to end).
"""

import re

from llm import get_llm_config, llm_chat
from tools import check_eligibility, load_schemes, search_schemes, web_search

SYSTEM_PROMPT = """You are SevaAgent, a helpful assistant that explains Indian
government welfare schemes in plain, simple language. The user may be a
villager, a daily-wage worker or a first-time internet user — use short
sentences and simple words. No jargon.

Rules:
- Answer ONLY from the scheme facts and web results given to you.
  Never invent a benefit amount, a date, a website or an eligibility rule.
- Answer in the user's language: Hindi if they wrote in Hindi, else English.
- For each scheme you mention, give: what you get, who can get it, and
  the official portal. Keep it short.
- If the eligibility check says the person may not be eligible, say so
  plainly and say why.
- End with one line: "Please confirm the latest details on the official
  portal before applying — rules change from time to time."
- Never ask for Aadhaar number, OTP, bank password or any payment.
- If you do not know something, say so instead of guessing.
"""

ELIGIBILITY_WORDS = [
    "eligib", "qualify", "can i get", "am i eligible", "do i qualify",
    "mere liye", "mujhe milega", "check", "पात्र", "योग्य", "मिलेगा",
    "मिलेगी", "मुझे", "मेरे लिए",
]
LATEST_WORDS = ["latest", "news", "update", "new", "2026", "taaza", "ताज़ा", "नया", "खबर"]

# A few state names for hint extraction (the UI also has a state dropdown).
STATE_WORDS = {
    "uttar pradesh": "Uttar Pradesh", "up": "Uttar Pradesh",
    "bihar": "Bihar", "maharashtra": "Maharashtra", "madhya pradesh": "Madhya Pradesh",
    "rajasthan": "Rajasthan", "gujarat": "Gujarat", "west bengal": "West Bengal",
    "tamil nadu": "Tamil Nadu", "karnataka": "Karnataka", "kerala": "Kerala",
    "odisha": "Odisha", "punjab": "Punjab", "haryana": "Haryana",
    "jharkhand": "Jharkhand", "assam": "Assam", "chhattisgarh": "Chhattisgarh",
    "telangana": "Telangana", "andhra pradesh": "Andhra Pradesh",
    "himachal": "Himachal Pradesh", "uttarakhand": "Uttarakhand",
    "delhi": "Delhi", "goa": "Goa", "jammu": "Jammu and Kashmir",
}


def is_hindi(text):
    """True if the message contains Devanagari characters."""
    return bool(re.search(r"[\u0900-\u097F]", text))


def extract_profile_hints(text, profile):
    """Pull age / income / state hints out of free text into the profile."""
    low = text.lower()
    m = re.search(r"(\d{1,3})\s*(?:years? old|yrs? old|saal|year old|age)", low)
    if m:
        profile["age"] = int(m.group(1))
    m = re.search(r"(?:income|salary|kamai|kamata|earn)[^\d]{0,20}?(\d+(?:\.\d+)?)\s*(lakh|lac|thousand|k)?", low)
    if m:
        val, unit = float(m.group(1)), (m.group(2) or "")
        profile["annual_income"] = int(val * 100000 if unit in ("lakh", "lac") else val * 1000 if unit in ("thousand", "k") else val)
    else:
        m = re.search(r"₹\s*(\d+(?:\.\d+)?)\s*(lakh|lac)?", low)
        if m and ("income" in low or "salary" in low or "kamai" in low):
            val = float(m.group(1))
            profile["annual_income"] = int(val * 100000 if m.group(2) else val)
    for word, state in STATE_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            profile["state"] = state
            break
    if any(w in low for w in ["daughter", "beti", "girl child", "ladki", "बेटी", "लड़की"]):
        profile["has_girl_child"] = True
    if any(w in low for w in ["farmer", "kisan", "kheti", "farming", "किसान", "खेती"]):
        profile["is_farmer"] = True
        profile["occupation"] = "farmer"
    if any(w in low for w in ["student", "padhai", "school", "college", "chhatra", "छात्र", "पढ़ाई", "विद्यार्थी"]):
        profile["is_student"] = True
        profile["occupation"] = "student"
    if any(w in low for w in ["carpenter", "tailor", "potter", "blacksmith", "mason", "barber", "artisan", "karigar", "darzi", "lohar", "कारीगर", "दर्जी", "बढ़ई", "लोहार"]):
        profile["is_artisan"] = True
        profile["occupation"] = "artisan"
    if any(w in low for w in ["shop", "dukan", "business", "vyapar", "startup", "व्यवसाय", "धंधा", "दुकान", "व्यापार"]):
        profile["has_business"] = True
        profile["occupation"] = "business_owner"
    return profile


def _scheme_block(s):
    e = s["eligibility"]
    lines = [f"- {s['name']} — {s['benefit_short']}."]
    lines.append(f"  What you get: {s['benefit']}")
    if e.get("min_age") is not None and e.get("max_age") is not None:
        lines.append(f"  Age: {e['min_age']} to {e['max_age']} years")
    elif e.get("min_age") is not None:
        lines.append(f"  Age: {e['min_age']} years or above")
    elif e.get("max_age") is not None:
        lines.append(f"  Age: up to {e['max_age']} years")
    if e.get("max_family_income_inr"):
        lines.append(f"  Family income: up to ₹{e['max_family_income_inr']:,}/year")
    lines.append(f"  Official portal: {s['official_portal']}")
    return "\n".join(lines)


def _template_answer(matches, elig_results, web_results, hindi, query):
    """Demo-mode answer built from tool outputs (no LLM needed)."""
    if hindi:
        out = ["नमस्ते! आपकी मदद के लिए मुझे यह जानकारी मिली है:\n"]
    else:
        out = ["Here is what I found for you:\n"]

    # Don't show detail blocks for schemes the person is definitely
    # not eligible for (when at least one other match remains).
    if elig_results:
        blocked = {r["scheme"]["id"] for r in elig_results if r["status"] == "not_eligible"}
        keep = [(s, sc) for s, sc in matches if s["id"] not in blocked]
        if keep:
            matches = keep

    shown = 0
    for s, _score in matches:
        out.append(_scheme_block(s))
        shown += 1
    if shown == 0 and not elig_results:
        if hindi:
            out.append("मुझे आपके सवाल से जुड़ी कोई योजना अपने डेटा में नहीं मिली। कृपया योजना का नाम या अपनी स्थिति (उम्र, काम, राज्य) थोड़े विस्तार से लिखें।")
        else:
            out.append("I could not find a scheme matching your question in my data. "
                       "Please tell me a little more — for example your age, your work, "
                       "or the name of the scheme you heard about.")
    if elig_results:
        elig = [r for r in elig_results if r["status"] in ("eligible", "likely")]
        if elig:
            out.append("\n**Schemes you may be eligible for:**" if not hindi else "\n**आपको ये योजनाएँ मिल सकती हैं:**")
            for r in elig:
                s = r["scheme"]
                mark = "✅" if r["status"] == "eligible" else "✔️ (likely)"
                out.append(f"{mark} {s['name']} — {s['benefit_short']}")
                for flag, msg in r["reasons"]:
                    if flag == "no":
                        out.append(f"   ⚠️ {msg}")
                    elif flag == "check":
                        out.append(f"   • To confirm: {msg}")
        else:
            out.append("\nBased on the details you gave, none of the 13 schemes in my data "
                       "look like a clear match. That does not mean you get nothing — "
                       "please share more details (age, income, work, state) and I will check again."
                       if not hindi else
                       "\nआपके बताए विवरण के हिसाब से मेरी 13 योजनाओं में से कोई साफ़ मेल नहीं खाती। "
                       "कृपया उम्र, आय, काम और राज्य बताइए, मैं दोबारा जाँच करूँगा।")
    if web_results:
        out.append("\n**Latest from the web:**" if not hindi else "\n**इंटरनेट से ताज़ा जानकारी:**")
        for r in web_results:
            out.append(f"- {r['title']} ({r['url']})")
            if r.get("snippet"):
                out.append(f"  {r['snippet'][:240]}")
    out.append("\n---\nPlease confirm the latest details on the official portal before "
               "applying — rules change from time to time. SevaAgent is not a government "
               "service and never asks for OTP or bank details."
               if not hindi else
               "\n---\nआवेदन से पहले आधिकारिक पोर्टल पर ताज़ा जानकारी ज़रूर देख लें — नियम समय-समय पर बदलते हैं। "
               "SevaAgent सरकारी सेवा नहीं है और कभी OTP या बैंक डिटेल नहीं माँगता।")
    return "\n".join(out)


def answer(query, profile=None, history=None):
    """Answer one user message.

    Returns (reply_text, trace) where trace is a dict describing which
    tools ran and what they found (shown in the UI as 'How I answered').
    """
    profile = dict(profile or {})
    schemes = load_schemes()
    hindi = is_hindi(query)
    profile = extract_profile_hints(query, profile)

    trace = {"tools": [], "schemes_matched": [], "web_results": 0, "mode": "demo"}

    # Tool 1 — curated dataset
    matches = search_schemes(query, schemes)
    trace["tools"].append("scheme_dataset")
    trace["schemes_matched"] = [s["name"] for s, _ in matches]

    # Tool 2 — eligibility checker
    low = query.lower()
    wants_eligibility = any(w in low for w in ELIGIBILITY_WORDS)
    has_profile = any([
        profile.get("age") is not None,
        profile.get("annual_income") is not None,
        profile.get("is_farmer"), profile.get("is_student"),
        profile.get("is_artisan"), profile.get("has_girl_child"),
        profile.get("has_business"),
    ])
    elig_results = None
    if wants_eligibility or (has_profile and matches):
        elig_results = check_eligibility(profile, schemes)
        trace["tools"].append("eligibility_checker")

    # Tool 3 — web search (latest info, or nothing matched locally)
    wants_latest = any(w in low for w in LATEST_WORDS)
    web_results = []
    if wants_latest or not matches:
        web_results = web_search(query, max_results=3)
        trace["tools"].append("web_search")
        trace["web_results"] = len(web_results)

    # Compose the answer
    mode, config = get_llm_config()
    trace["mode"] = mode
    if mode != "demo":
        context = []
        for s, _ in matches:
            context.append(_scheme_block(s))
        if elig_results:
            elig = [r for r in elig_results if r["status"] in ("eligible", "likely")]
            if elig:
                context.append("Eligibility check for this person:")
                for r in elig:
                    context.append(f"- {r['scheme']['name']}: {r['status']}")
                    for flag, msg in r["reasons"]:
                        if flag != "yes":
                            context.append(f"  ({flag}) {msg}")
        if web_results:
            context.append("Latest web results:")
            for r in web_results:
                context.append(f"- {r['title']}: {r.get('snippet', '')} ({r['url']})")
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"User question: {query}\n\n"
                f"Facts from tools:\n" + ("\n".join(context) if context else "(no matching scheme found)")
            )},
        ]
        try:
            return llm_chat(messages, config), trace
        except Exception as exc:  # fall back to demo mode, never crash
            trace["llm_error"] = str(exc)[:200]
            trace["mode"] = "demo (LLM failed)"

    return _template_answer(matches, elig_results, web_results, hindi, query), trace
