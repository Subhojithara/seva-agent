# 🇮🇳 SevaAgent

**An open-source agentic AI assistant that helps Indian citizens discover
government welfare schemes and check their eligibility — in plain language.**

Built for the **Bharat Agentic-AI Hackathon (Code for India)** — an open-source
agentic-AI public good for India. Submissions close **15 November 2026**.

> Ask in English or Hindi: *"I am 72 years old. Which health scheme can I get?"*,
> *"मेरी बेटी 5 साल की है, उसके लिए कौन सी योजना है?"* — SevaAgent finds the
> right schemes, checks your eligibility, and points you to the official portal.

## What it does

- **Scheme discovery** — a curated, fact-checked dataset of **13 real Indian
  government schemes** (PM-JAY, Ayushman Vaya Vandana, PM-KISAN, PMAY-Gramin,
  PMAY-Urban 2.0, Sukanya Samriddhi, Atal Pension Yojana, PM Jan Dhan, National
  Scholarship Portal, PM Vishwakarma, PM Surya Ghar, PM Mudra, PM Fasal Bima).
  Every benefit amount and eligibility rule was verified against official
  sources in November 2026. No invented facts.
- **Eligibility checker (tool)** — matches a person's age, income, state,
  category, occupation and situation against each scheme's rules and explains
  *why* — eligible, likely, needs checking, or not eligible.
- **Web search (tool)** — DuckDuckGo search for the latest scheme news and
  updates, used when you ask for "latest" or when nothing in the dataset matches.
- **LLM, pluggable** — set `OPENAI_API_KEY` or `HF_TOKEN` and the agent's
  replies are written by the model from the tool results. **No key? No problem:**
  the app runs in demo mode, answering from the tools + templates, so it is
  fully demonstrable without spending anything.
- **Simple UI** — Gradio chat + an optional profile form (age, income, state,
  category, work) with a one-click eligibility check. Works in English and Hindi.

## How it works

```
User question
    │
    ├─► Tool 1: search curated schemes dataset (schemes.json)
    ├─► Tool 2: eligibility checker (profile → per-scheme verdict + reasons)
    ├─► Tool 3: DuckDuckGo web search (latest news / no local match)
    │
    └─► Answer: LLM (OpenAI / Hugging Face) writes from tool results,
        or template answer in demo mode. Every answer cites the official
        portal and reminds you to verify before applying.
```

## Run locally

```bash
git clone <your-repo-url>
cd seva-agent
python -m venv .venv
.venv/bin/pip install -r requirements.txt
python app.py
# open http://127.0.0.1:7860
```

Smoke test (no key needed — runs in demo mode):

```bash
.venv/bin/python test_agent.py
```

### Use an LLM (optional)

```bash
export OPENAI_API_KEY="sk-..."        # OpenAI, model via OPENAI_MODEL (default gpt-4o-mini)
# or
export HF_TOKEN="hf_..."              # Hugging Face Inference, model via HF_MODEL
                                       # (default meta-llama/Llama-3.1-8B-Instruct)
python app.py
```

## Deploy to Hugging Face Spaces (free)

1. Create a Space at https://huggingface.co/new-space → SDK **Gradio**.
2. Upload `app.py`, `agent.py`, `tools.py`, `llm.py`, `schemes.json`,
   `requirements.txt` (the Space installs them automatically).
3. Optional: in the Space **Settings → Secrets**, add `OPENAI_API_KEY` or
   `HF_TOKEN` to turn on LLM mode. Without secrets the Space still works in
   demo mode.

## Project structure

| File | What it is |
|---|---|
| `app.py` | Gradio UI (chat + profile form + eligibility check) |
| `agent.py` | The agent: language detection, profile hints, tool orchestration, answering |
| `tools.py` | Tool 1 dataset search, Tool 2 eligibility checker, Tool 3 web search |
| `llm.py` | Pluggable LLM (OpenAI / Hugging Face / demo) |
| `schemes.json` | Curated dataset of 13 real schemes, verified Nov 2026 |
| `test_agent.py` | Smoke tests (demo mode, no key needed) |
| `requirements.txt` | `gradio`, `requests`, `ddgs` |
| `LICENSE` | MIT |

## Accuracy & limits

- Scheme facts were checked against official portals and government sources
  in November 2026 (`schemes.json` → `meta.last_verified`). Rules change —
  the app always tells users to confirm on the official portal.
- The eligibility check is a **rough guide** from the details you give, not an
  official decision. Some rules (e.g. SECC 2011 listing) can only be confirmed
  on the official portal.
- SevaAgent never asks for Aadhaar, OTP, bank passwords or payments, and it
  cannot enrol anyone in a scheme.
- Demo mode answers from templates — accurate, but less fluent than LLM mode.

## License

MIT — see `LICENSE`. Built by Subhajit Hara (Velurix) for the Bharat
Agentic-AI Hackathon 2026.
