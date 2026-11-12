"""SevaAgent — Gradio web app.

An open-source agentic AI assistant that helps Indian citizens discover
government welfare schemes and check their eligibility, in plain language.

Run locally:
    python -m venv .venv && .venv/bin/pip install -r requirements.txt
    python app.py

LLM (optional — the app also works without one, in demo mode):
    export OPENAI_API_KEY="..."   # or
    export HF_TOKEN="..."         # Hugging Face Inference Providers

NOTE: some sandboxed environments set NO_PROXY with bracketed IPv6 entries
(e.g. [::1]) which makes httpx crash at gradio import time. We strip those
entries before importing gradio — harmless everywhere else.
"""

import os

for _k in ("no_proxy", "NO_PROXY"):
    _v = os.environ.get(_k, "")
    if _v:
        os.environ[_k] = ",".join(
            p for p in _v.split(",")
            if not (p.strip().startswith("[") and p.strip().endswith("]"))
        )

import gradio as gr

# On Hugging Face Spaces (ZeroGPU) the chat handler runs on GPU; locally the
# `spaces` package is absent, so fall back to a no-op decorator.
try:
    import spaces
    _gpu = spaces.GPU(duration=120)
except ImportError:
    def _gpu(fn):
        return fn

from agent import answer, is_hindi
from llm import get_llm_config
from tools import (
    INDIAN_STATES,
    OCCUPATIONS,
    check_eligibility,
    empty_profile,
    load_schemes,
)

MODE, _CFG = get_llm_config()
SCHEME_COUNT = len(load_schemes())

MODE_TEXT = {
    "openai": "🤖 LLM mode: OpenAI (answers written by the model from tool results)",
    "hf": "🤖 LLM mode: Hugging Face Inference (answers written by the model from tool results)",
    "demo": "📋 Demo mode: no API key set — answers come from the curated scheme data + templates",
}[MODE]

TITLE = "🇮🇳 SevaAgent — सरकारी योजनाएँ, आसान भाषा में"
DESCRIPTION = f"""
Ask in English or Hindi about any government welfare scheme — health, pension,
housing, scholarships, farming, business loans, solar subsidy and more.
SevaAgent searches **{SCHEME_COUNT} real schemes**, checks what **you** may be eligible for,
and looks up the latest information on the web when needed.

Fill in your details on the left (optional) for a personal eligibility check.
SevaAgent never asks for Aadhaar, OTP or bank details, and it is **not** a government service —
always confirm the latest rules on the official portal before applying.
"""


def build_profile(age, income, state, category, gender, occupation,
                  is_farmer, has_girl_child, is_student, is_artisan,
                  own_house, has_bank_account, area, secc, has_business):
    p = empty_profile()
    p["age"] = int(age) if age else None
    p["annual_income"] = int(income) if income else None
    p["state"] = state or ""
    p["category"] = "any" if category in (None, "", "Not sure") else category
    p["gender"] = {"Female": "female", "Male": "male"}.get(gender, "any")
    p["occupation"] = occupation or "other"
    p["is_farmer"] = bool(is_farmer)
    p["has_girl_child"] = bool(has_girl_child)
    p["is_student"] = bool(is_student)
    p["is_artisan"] = bool(is_artisan)
    p["own_house"] = bool(own_house)
    p["has_bank_account"] = bool(has_bank_account)
    p["area"] = {"Rural (village)": "rural", "Urban (town / city)": "urban"}.get(area, "")
    p["secc_listed"] = {"Yes, my family is listed": True, "No, not listed": False}.get(secc)
    p["has_business"] = bool(has_business)
    return p


def format_eligibility(results):
    lines = ["### Your eligibility check\n"]
    groups = {
        "eligible": ("✅ Looks eligible", []),
        "likely": ("✔️ Likely eligible — a few things to confirm", []),
        "check": ("❓ Cannot tell yet — needs more details", []),
        "not_eligible": ("❌ Probably not eligible", []),
    }
    for r in results:
        groups[r["status"]][1].append(r)
    for status, (heading, items) in groups.items():
        if not items:
            continue
        lines.append(f"**{heading}**")
        for r in items:
            s = r["scheme"]
            lines.append(f"- **{s['name']}** — {s['benefit_short']} "
                         f"([official portal]({s['official_portal']}))")
            for flag, msg in r["reasons"]:
                if flag == "no":
                    lines.append(f"  - ⚠️ {msg}")
                elif flag == "check":
                    lines.append(f"  - • To confirm: {msg}")
        lines.append("")
    lines.append("_This is a rough check from the details you gave, not an official decision. "
               "Final eligibility is decided by the scheme's own process._")
    return "\n".join(lines)


def check_my_eligibility(age, income, state, category, gender, occupation,
                         is_farmer, has_girl_child, is_student, is_artisan,
                         own_house, has_bank_account, area, secc, has_business):
    profile = build_profile(age, income, state, category, gender, occupation,
                            is_farmer, has_girl_child, is_student, is_artisan,
                            own_house, has_bank_account, area, secc, has_business)
    if profile["age"] is None and profile["annual_income"] is None \
            and not any([is_farmer, has_girl_child, is_student, is_artisan, has_business]):
        return ("Please fill in at least one detail on the left — for example your age, "
                "your yearly family income, or tick what applies to you — then press the button again.")
    return format_eligibility(check_eligibility(profile))


@_gpu
def chat_reply(message, history, age, income, state, category, gender, occupation,
               is_farmer, has_girl_child, is_student, is_artisan,
               own_house, has_bank_account, area, secc, has_business):
    if not message or not message.strip():
        return history, ""
    profile = build_profile(age, income, state, category, gender, occupation,
                            is_farmer, has_girl_child, is_student, is_artisan,
                            own_house, has_bank_account, area, secc, has_business)
    reply, trace = answer(message, profile)
    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ]
    tools_used = ", ".join(trace["tools"])
    trace_text = (
        f"🔧 Tools used: {tools_used}  •  Mode: {trace['mode']}  •  "
        f"Schemes matched: {', '.join(trace['schemes_matched']) or 'none'}"
        + (f"  •  Web results: {trace['web_results']}" if "web_search" in trace["tools"] else "")
        + (f"  •  ⚠️ LLM error: {trace['llm_error']}" if trace.get("llm_error") else "")
    )
    return history, trace_text


PROFILE_INPUTS = []

with gr.Blocks(title="SevaAgent") as demo:
    gr.Markdown(f"# {TITLE}")
    gr.Markdown(DESCRIPTION)
    gr.Markdown(f"*{MODE_TEXT}*")

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 👤 Your details (optional)")
            age_in = gr.Number(label="Your age (years)", precision=0)
            income_in = gr.Number(label="Family income per year (₹)", precision=0)
            state_in = gr.Dropdown([""] + INDIAN_STATES, label="State", value="")
            category_in = gr.Radio(
                ["Not sure", "General", "SC", "ST", "OBC", "Minority"],
                label="Category", value="Not sure")
            gender_in = gr.Radio(
                ["Prefer not to say", "Female", "Male"],
                label="Gender", value="Prefer not to say")
            occupation_in = gr.Dropdown(
                [(label, value) for value, label in OCCUPATIONS],
                label="Your work", value="other")
            area_in = gr.Radio(
                ["Not sure", "Rural (village)", "Urban (town / city)"],
                label="Where do you live?", value="Not sure")
            secc_in = gr.Radio(
                ["I don't know", "Yes, my family is listed", "No, not listed"],
                label="Is your family in the SECC 2011 list? (for Ayushman / Awas)",
                value="I don't know")
            farmer_in = gr.Checkbox(label="I am a farmer / own farmland")
            girl_in = gr.Checkbox(label="Girl child below 10 in my family")
            student_in = gr.Checkbox(label="I am a student")
            artisan_in = gr.Checkbox(label="I am an artisan / craftsperson (18 traditional trades)")
            business_in = gr.Checkbox(label="I run a small business / shop")
            house_in = gr.Checkbox(label="I own a house with a roof (for solar)")
            bank_in = gr.Checkbox(label="I have a bank / post office account")
            PROFILE_INPUTS = [age_in, income_in, state_in, category_in, gender_in,
                              occupation_in, farmer_in, girl_in, student_in, artisan_in,
                              house_in, bank_in, area_in, secc_in, business_in]
            check_btn = gr.Button("✅ Check my eligibility", variant="primary")
            elig_out = gr.Markdown()

        with gr.Column(scale=2):
            gr.Markdown("### 💬 Ask SevaAgent")
            chatbot = gr.Chatbot(label="SevaAgent", height=520)
            msg = gr.Textbox(
                label="Your question",
                placeholder="e.g. I am 72 years old. Which health scheme can I get?  /  मेरी बेटी 5 साल की है, उसके लिए कौन सी योजना है?",
            )
            with gr.Row():
                send_btn = gr.Button("Send", variant="primary")
                clear_btn = gr.Button("Clear chat")
            trace_out = gr.Markdown()
            gr.Examples(
                examples=[
                    "I am 72 years old. Which health scheme can I get?",
                    "My daughter is 5 years old, is there a savings scheme for her?",
                    "I am a farmer with 2 acres of land. What help can I get?",
                    "Am I eligible for a house under PM Awas Yojana? I earn 2 lakh a year.",
                    "What is the latest news on PM Surya Ghar solar subsidy?",
                    "मुझे अपने छोटे व्यवसाय के लिए लोन चाहिए। कौन सी योजना है?",
                    "I am a tailor. Is there any scheme for artisans?",
                ],
                inputs=msg,
            )

    check_btn.click(
        check_my_eligibility, inputs=PROFILE_INPUTS, outputs=elig_out,
    )
    msg.submit(
        chat_reply, inputs=[msg, chatbot] + PROFILE_INPUTS,
        outputs=[chatbot, trace_out], api_name="chat",
    ).then(lambda: "", outputs=msg)
    send_btn.click(
        chat_reply, inputs=[msg, chatbot] + PROFILE_INPUTS,
        outputs=[chatbot, trace_out],
    ).then(lambda: "", outputs=msg)
    clear_btn.click(lambda: [], outputs=chatbot)

    gr.Markdown(
        "---\n**Disclaimer:** SevaAgent gives general information about government schemes. "
        "It is not a government service, it cannot enrol you, and it never asks for Aadhaar, "
        "OTP or bank details. Scheme rules change — confirm the latest details on the official "
        "portal before applying. Data last verified: 12 Nov 2026."
    )


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
