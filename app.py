"""
JD -> Tailored Resume + Cover Letter — backend (OpenAI).
Runs locally, on Replit, or on Vercel. Default model: gpt-4o-mini.

Key modes:
  * BYOK (safe for public sharing): each user pastes their own OpenAI key in the
    UI. Sent per-request as X-User-Key, used to call the API, never stored server-side.
  * Host-pays: set OPENAI_API_KEY on the server; users leave the field blank and
    YOU pay. Only do this behind a usage limit (and ideally a gate) — see README.
"""
import os
from pathlib import Path
from fastapi import FastAPI, Header
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from openai import OpenAI

# Default to a cheap, stable chat model. To use a newer model (e.g. gpt-5.5 /
# gpt-5.4-mini), just change this string — the token-param fallback below handles
# the older vs newer parameter name automatically.
MODEL = "gpt-4o-mini"
SERVER_KEY = os.environ.get("OPENAI_API_KEY")  # optional host-pays fallback
app = FastAPI(title="Resume Tailor")


def run_llm(user_key, system, user, max_out=2000):
    key = (user_key or "").strip() or SERVER_KEY
    if not key:
        raise ValueError("No API key provided. Paste your OpenAI API key in the field at the top.")
    client = OpenAI(api_key=key)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        # Newer models expect max_completion_tokens...
        resp = client.chat.completions.create(model=MODEL, messages=messages, max_completion_tokens=max_out)
    except Exception:
        # ...older chat models (e.g. gpt-4o-mini) use max_tokens.
        resp = client.chat.completions.create(model=MODEL, messages=messages, max_tokens=max_out)
    return (resp.choices[0].message.content or "").strip()


# ---- Prompts (server-side) ------------------------------------------------------
ANALYSIS_SYS = """You assess fit between a candidate's resume and a job description for any role or industry.
Pull the key requirements from the JD (max 12 - the ones that drive shortlisting).
Classify each: "matched" = clearly evidenced in the resume; "partial" = adjacent/transferable but not explicit; "missing" = genuinely absent.
Give an alignment score 0-100 reflecting realistic shortlisting odds (weight must-haves heavily; be honest, don't inflate).
For items worth closing, add a short concrete prep note.
Output ONLY valid JSON - no markdown, no prose - exactly this shape:
{"required":["..."],"matched":["..."],"partial":["..."],"missing":["..."],"score":0,"to_gain":[{"skill":"...","how":"..."}]}"""

RESUME_SYS = """You are an expert resume editor who tailors resumes for any role or industry.
You tailor an existing master resume to a JD by REORDERING and RE-EMPHASIZING content already present - you NEVER invent skills, employers, projects, tools, or metrics the candidate lacks.
Rules: (1) every claim traces to the master resume; (2) reorder bullets and skills so the most JD-relevant come first; (3) rephrase to mirror JD terminology ONLY where it stays accurate; (4) one page, ATS-friendly plain text, same sections; (5) obey extra instructions; (6) never fake a missing requirement.
Output the full tailored resume as plain text. Then a line with exactly ===CHANGES=== then 3-6 short bullets describing ONLY what you moved up / re-emphasized / reworded (no gaps here)."""

COVER_SYS = """You are an expert cover-letter writer for any role or industry.
Write a concise (180-260 words), specific, non-generic letter grounded ENTIRELY in the resume - no fabrication.
Tie 2-3 of the candidate's most relevant real achievements to the role's needs. Professional, warm, confident, plain - no "I am writing to express", no filler. Use company/role if given. End with the candidate's name on its own line. Output only the letter."""


# ---- Schemas --------------------------------------------------------------------
class AnalyzeIn(BaseModel):
    jd: str; resume: str

class TailorIn(BaseModel):
    jd: str; resume: str; comments: str = ""

class CoverIn(BaseModel):
    jd: str; resume: str; company: str = ""; role: str = ""; comments: str = ""


# ---- Endpoints ------------------------------------------------------------------
@app.post("/api/analyze")
def analyze(b: AnalyzeIn, x_user_key: str | None = Header(default=None)):
    import json, re
    try:
        raw = run_llm(x_user_key, ANALYSIS_SYS, f"JOB DESCRIPTION:\n{b.jd}\n\nRESUME:\n{b.resume}", 1500)
        raw = re.sub(r"```json|```", "", raw).strip()
        return JSONResponse(json.loads(raw))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

@app.post("/api/tailor")
def tailor(b: TailorIn, x_user_key: str | None = Header(default=None)):
    try:
        out = run_llm(x_user_key, RESUME_SYS,
            f"JOB DESCRIPTION:\n{b.jd}\n\nMASTER RESUME:\n{b.resume}\n\nEXTRA INSTRUCTIONS:\n{b.comments or '(none)'}", 2400)
        body, changes = out, ""
        if "===CHANGES===" in out:
            body, changes = out.split("===CHANGES===", 1)
        return {"resume": body.strip(), "changes": changes.strip()}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

@app.post("/api/cover")
def cover(b: CoverIn, x_user_key: str | None = Header(default=None)):
    try:
        user = (f"JOB DESCRIPTION:\n{b.jd}\n\nCANDIDATE RESUME:\n{b.resume}\n\n"
                f"COMPANY: {b.company or '(see JD)'}\nROLE: {b.role or '(see JD)'}\n"
                f"EXTRA INSTRUCTIONS:\n{b.comments or '(none)'}")
        return {"letter": run_llm(x_user_key, COVER_SYS, user, 1200)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

@app.get("/", response_class=HTMLResponse)
def index():
    return Path(__file__).with_name("index.html").read_text(encoding="utf-8")
