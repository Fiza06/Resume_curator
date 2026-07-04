"""
JD -> Tailored Resume + Cover Letter — backend (OpenAI).
Runs locally, on Replit, or on Vercel. Default model: gpt-4o-mini.

Key modes:
  * Server-key mode: set OPENAI_API_KEY in the server environment. Users never
    see or provide API keys. Keep this behind auth, usage limits, and billing.
"""
import os
import re
from html import escape
from io import BytesIO
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
from openai import OpenAI

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Default to a cheap, stable chat model. To use a newer model (e.g. gpt-5.5 /
# gpt-5.4-mini), just change this string — the token-param fallback below handles
# the older vs newer parameter name automatically.
MODEL = "gpt-4o-mini"
SERVER_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
APP_MODE = os.environ.get("APP_MODE", "free").strip().lower()
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
STRIPE_PRICE_STARTER = os.environ.get("STRIPE_PRICE_STARTER", "").strip()
STRIPE_PRICE_PRO = os.environ.get("STRIPE_PRICE_PRO", "").strip()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "").strip()
app = FastAPI(title="Resume Tailor")


PLAN_CATALOG = [
    {
        "id": "free",
        "name": "Free Beta",
        "price": "Free",
        "interval": None,
        "description": "Unlimited access while the product is in beta.",
        "features": ["Resume tailoring", "Cover letters", "Analysis preview"],
        "active": True,
    },
    {
        "id": "starter",
        "name": "Starter",
        "price": "To be configured",
        "interval": "month",
        "description": "Future paid plan for casual job search workflows.",
        "features": ["Saved resume history", "PDF exports", "Template library"],
        "active": False,
    },
    {
        "id": "pro",
        "name": "Pro",
        "price": "To be configured",
        "interval": "month",
        "description": "Future paid plan for frequent applications and premium analysis.",
        "features": ["Advanced analysis", "Higher export limits", "Priority features"],
        "active": False,
    },
]

PDF_TEMPLATES = {
    "classic": {
        "name": "Classic ATS",
        "best_for": "General applications",
        "accent": "#1F4E79",
        "font": "Helvetica",
        "margins": (54, 46, 54, 46),
    },
    "modern": {
        "name": "Modern",
        "best_for": "Product, data, business roles",
        "accent": "#0F766E",
        "font": "Helvetica",
        "margins": (48, 42, 48, 42),
    },
    "technical": {
        "name": "Technical",
        "best_for": "Engineering and AI roles",
        "accent": "#334155",
        "font": "Courier",
        "margins": (42, 38, 42, 38),
    },
    "academic": {
        "name": "Academic",
        "best_for": "Research, education, publications",
        "accent": "#7C2D12",
        "font": "Times-Roman",
        "margins": (54, 48, 54, 48),
    },
    "executive": {
        "name": "Executive",
        "best_for": "Senior and leadership roles",
        "accent": "#4338CA",
        "font": "Helvetica",
        "margins": (58, 50, 58, 50),
    },
}


def payments_enabled():
    return bool(STRIPE_SECRET_KEY and (STRIPE_PRICE_STARTER or STRIPE_PRICE_PRO))


def price_id_for(plan_id):
    return {
        "starter": STRIPE_PRICE_STARTER,
        "pro": STRIPE_PRICE_PRO,
    }.get(plan_id, "")


def run_llm(system, user, max_out=2000):
    if not SERVER_KEY:
        raise ValueError("Server OpenAI key is not configured. Set OPENAI_API_KEY in the server environment.")
    client = OpenAI(api_key=SERVER_KEY)
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

class CheckoutIn(BaseModel):
    plan_id: str
    success_url: str
    cancel_url: str

class PdfExportIn(BaseModel):
    resume: str
    template_id: str = "classic"
    title: str = "resume"


# ---- Endpoints ------------------------------------------------------------------
@app.get("/api/export/templates")
def export_templates():
    return {
        "templates": [
            {"id": key, "name": value["name"], "best_for": value["best_for"]}
            for key, value in PDF_TEMPLATES.items()
        ]
    }

def pdf_filename(title):
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", (title or "resume").strip()).strip("_")
    return (name or "resume")[:60] + ".pdf"

def is_section(line):
    clean = re.sub(r"[^A-Za-z &/+-]", "", line).strip()
    if not clean or len(clean) > 42:
        return False
    return clean.upper() == clean and any(c.isalpha() for c in clean)

def build_resume_pdf(text, template_id):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    config = PDF_TEMPLATES.get(template_id) or PDF_TEMPLATES["classic"]
    left, top, right, bottom = config["margins"]
    accent = colors.HexColor(config["accent"])
    font = config["font"]
    bold_font = {
        "Helvetica": "Helvetica-Bold",
        "Courier": "Courier-Bold",
        "Times-Roman": "Times-Bold",
    }.get(font, "Helvetica-Bold")

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=left,
        rightMargin=right,
        topMargin=top,
        bottomMargin=bottom,
        title="Resume",
    )
    base = getSampleStyleSheet()
    styles = {
        "name": ParagraphStyle("Name", parent=base["Normal"], fontName=bold_font, fontSize=18, leading=22, textColor=accent, alignment=TA_CENTER, spaceAfter=3),
        "contact": ParagraphStyle("Contact", parent=base["Normal"], fontName=font, fontSize=8.5, leading=11, alignment=TA_CENTER, textColor=colors.HexColor("#475569"), spaceAfter=8),
        "section": ParagraphStyle("Section", parent=base["Normal"], fontName=bold_font, fontSize=10.5, leading=13, textColor=accent, spaceBefore=8, spaceAfter=3),
        "body": ParagraphStyle("Body", parent=base["Normal"], fontName=font, fontSize=9, leading=11.6, textColor=colors.HexColor("#111827"), spaceAfter=3),
        "bullet": ParagraphStyle("Bullet", parent=base["Normal"], fontName=font, fontSize=8.8, leading=11.2, leftIndent=12, firstLineIndent=-8, spaceAfter=2),
    }
    if template_id == "executive":
        styles["name"].fontSize = 20
        styles["section"].fontSize = 11
        styles["body"].fontSize = 9.4
    if template_id == "technical":
        styles["name"].fontSize = 16
        styles["body"].fontSize = 8.5
        styles["bullet"].fontSize = 8.3

    lines = [line.strip() for line in (text or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        lines = ["Resume"]

    story = []
    name = lines[0]
    contact = lines[1] if len(lines) > 1 and not is_section(lines[1]) else ""
    start = 2 if contact else 1

    if template_id == "modern":
        header = Table([[Paragraph(escape(name), styles["name"])], [Paragraph(escape(contact), styles["contact"]) if contact else ""]], colWidths=[doc.width])
        header.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ECFDF5")),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#99F6E4")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(header)
        story.append(Spacer(1, 8))
    else:
        story.append(Paragraph(escape(name), styles["name"]))
        if contact:
            story.append(Paragraph(escape(contact), styles["contact"]))
        story.append(HRFlowable(width="100%", thickness=1, color=accent, spaceBefore=2, spaceAfter=6))

    for line in lines[start:]:
        safe = escape(line)
        bullet = line.lstrip("•-* ").strip()
        if is_section(line):
            story.append(Paragraph(safe, styles["section"]))
            if template_id in {"academic", "executive"}:
                story.append(HRFlowable(width="100%", thickness=0.4, color=accent, spaceBefore=0, spaceAfter=3))
        elif line.startswith(("•", "-", "*")):
            story.append(Paragraph("&bull; " + escape(bullet), styles["bullet"]))
        else:
            story.append(Paragraph(safe, styles["body"]))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()

@app.post("/api/export/pdf")
def export_pdf(b: PdfExportIn):
    if not b.resume.strip():
        return JSONResponse({"error": "No resume text provided."}, status_code=400)
    try:
        pdf = build_resume_pdf(b.resume, b.template_id)
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{pdf_filename(b.title)}"'},
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

@app.get("/api/billing/config")
def billing_config():
    configured_prices = {"starter": bool(STRIPE_PRICE_STARTER), "pro": bool(STRIPE_PRICE_PRO)}
    plans = []
    for plan in PLAN_CATALOG:
        item = dict(plan)
        item["stripe_configured"] = plan["id"] == "free" or configured_prices.get(plan["id"], False)
        plans.append(item)
    return {
        "mode": APP_MODE,
        "free_access": APP_MODE == "free",
        "payments_enabled": payments_enabled(),
        "plans": plans,
    }

@app.get("/api/supabase/config")
def supabase_config():
    configured = bool(SUPABASE_URL and SUPABASE_ANON_KEY)
    return {
        "configured": configured,
        "url": SUPABASE_URL if configured else "",
        "anon_key": SUPABASE_ANON_KEY if configured else "",
    }

@app.post("/api/billing/checkout")
def create_checkout(b: CheckoutIn):
    plan_id = b.plan_id.strip().lower()
    if plan_id == "free":
        return {"checkout_url": None, "message": "Free access is currently active."}
    price_id = price_id_for(plan_id)
    if not STRIPE_SECRET_KEY or not price_id:
        return JSONResponse({
            "error": "Payments are not enabled yet. Configure STRIPE_SECRET_KEY and the plan price id to activate checkout."
        }, status_code=400)
    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=b.success_url,
            cancel_url=b.cancel_url,
            allow_promotion_codes=True,
        )
        return {"checkout_url": session.url}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

@app.post("/api/analyze")
def analyze(b: AnalyzeIn):
    import json, re
    try:
        raw = run_llm(ANALYSIS_SYS, f"JOB DESCRIPTION:\n{b.jd}\n\nRESUME:\n{b.resume}", 1500)
        raw = re.sub(r"```json|```", "", raw).strip()
        return JSONResponse(json.loads(raw))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

@app.post("/api/tailor")
def tailor(b: TailorIn):
    try:
        out = run_llm(RESUME_SYS,
            f"JOB DESCRIPTION:\n{b.jd}\n\nMASTER RESUME:\n{b.resume}\n\nEXTRA INSTRUCTIONS:\n{b.comments or '(none)'}", 2400)
        body, changes = out, ""
        if "===CHANGES===" in out:
            body, changes = out.split("===CHANGES===", 1)
        return {"resume": body.strip(), "changes": changes.strip()}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

@app.post("/api/cover")
def cover(b: CoverIn):
    try:
        user = (f"JOB DESCRIPTION:\n{b.jd}\n\nCANDIDATE RESUME:\n{b.resume}\n\n"
                f"COMPANY: {b.company or '(see JD)'}\nROLE: {b.role or '(see JD)'}\n"
                f"EXTRA INSTRUCTIONS:\n{b.comments or '(none)'}")
        return {"letter": run_llm(COVER_SYS, user, 1200)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

@app.get("/", response_class=HTMLResponse)
def index():
    return Path(__file__).with_name("index.html").read_text(encoding="utf-8")
