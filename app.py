"""
JD -> Tailored Resume + Cover Letter — backend (OpenAI).
Runs locally, on Replit, or on Vercel. Default model: gpt-4o-mini.

Key modes:
  * Server-key mode: set OPENAI_API_KEY in the server environment. Users never
    see or provide API keys. Keep this behind auth, usage limits, and billing.
"""
import os
import re
from datetime import datetime, timezone
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
from openai import OpenAI
import httpx
import jwt

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Free tier uses a cheap model; Pro subscribers get a stronger one. The
# token-param fallback in run_llm() handles the older vs newer parameter name
# automatically for either model.
MODEL_FREE = "gpt-4o-mini"
MODEL_PRO = "gpt-4o"
MODEL = MODEL_FREE  # kept for any external references to the old default
FREE_MATCH_LIMIT = 3
SERVER_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
APP_MODE = os.environ.get("APP_MODE", "free").strip().lower()
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
STRIPE_PRICE_PRO_MONTHLY = os.environ.get("STRIPE_PRICE_PRO_MONTHLY", "").strip()
STRIPE_PRICE_PRO_ANNUAL = os.environ.get("STRIPE_PRICE_PRO_ANNUAL", "").strip()
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "").strip()
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
app = FastAPI(title="Resume Tailor")


PLAN_CATALOG = [
    {
        "id": "free",
        "name": "Free",
        "price": "$0",
        "interval": "forever",
        "description": "For your next application.",
        "features": ["3 resume matches / month", "Fit score & top 3 gaps", "5 AI-rewritten bullets"],
        "active": True,
    },
    {
        "id": "pro",
        "name": "Pro",
        "price": "$12",
        "interval": "month, billed annually",
        "description": "For an active job search.",
        "features": [
            "Unlimited resume matches",
            "Full gap analysis with priorities",
            "Unlimited AI-rewritten bullets",
            "ATS keyword & PDF export",
            "Cover-letter draft generator",
            "Version history & saved jobs",
            "Priority model access",
        ],
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
    return bool(STRIPE_SECRET_KEY and (STRIPE_PRICE_PRO_MONTHLY or STRIPE_PRICE_PRO_ANNUAL))


def price_id_for(plan_id, interval="annual"):
    if plan_id != "pro":
        return ""
    return STRIPE_PRICE_PRO_ANNUAL if interval == "annual" else STRIPE_PRICE_PRO_MONTHLY


def run_llm(system, user, max_out=2000, model=None):
    if not SERVER_KEY:
        raise ValueError("Server OpenAI key is not configured. Set OPENAI_API_KEY in the server environment.")
    client = OpenAI(api_key=SERVER_KEY)
    use_model = model or MODEL_FREE
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        # Newer models expect max_completion_tokens...
        resp = client.chat.completions.create(model=use_model, messages=messages, max_completion_tokens=max_out)
    except Exception:
        # ...older chat models (e.g. gpt-4o-mini) use max_tokens.
        resp = client.chat.completions.create(model=use_model, messages=messages, max_tokens=max_out)
    return (resp.choices[0].message.content or "").strip()


# ---- Auth + billing/quota helpers ------------------------------------------------
def resolve_user(authorization):
    """Decode a Supabase access token from an `Authorization: Bearer <jwt>` header.
    Returns {"id": ..., "email": ...} or None (anonymous / not configured)."""
    if not authorization or not SUPABASE_JWT_SECRET:
        return None
    token = authorization[7:] if authorization.lower().startswith("bearer ") else authorization
    try:
        payload = jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated")
    except Exception:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    return {"id": user_id, "email": payload.get("email", "")}


def supabase_admin_enabled():
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def _supabase_admin_headers():
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def current_period():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def get_user_billing(user_id):
    if not supabase_admin_enabled():
        return None
    try:
        r = httpx.get(
            f"{SUPABASE_URL}/rest/v1/user_billing",
            params={"user_id": f"eq.{user_id}", "select": "*"},
            headers=_supabase_admin_headers(),
            timeout=8,
        )
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None
    except Exception:
        return None


def get_usage_count(user_id, period):
    if not supabase_admin_enabled():
        return 0
    try:
        r = httpx.get(
            f"{SUPABASE_URL}/rest/v1/usage_counters",
            params={"user_id": f"eq.{user_id}", "period": f"eq.{period}", "select": "match_count"},
            headers=_supabase_admin_headers(),
            timeout=8,
        )
        r.raise_for_status()
        rows = r.json()
        return rows[0]["match_count"] if rows else 0
    except Exception:
        return 0


def increment_usage(user_id, period):
    if not supabase_admin_enabled():
        return None
    try:
        r = httpx.post(
            f"{SUPABASE_URL}/rest/v1/rpc/increment_usage",
            json={"p_user_id": user_id, "p_period": period},
            headers=_supabase_admin_headers(),
            timeout=8,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def upsert_user_billing(user_id, **fields):
    if not supabase_admin_enabled() or not user_id:
        return
    try:
        httpx.post(
            f"{SUPABASE_URL}/rest/v1/user_billing",
            json={"user_id": user_id, **fields},
            headers={**_supabase_admin_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"},
            params={"on_conflict": "user_id"},
            timeout=8,
        )
    except Exception:
        pass


def resolve_plan(user):
    """Returns (plan_id, model, matches_used, matches_limit) for the resolved user (or None)."""
    if not user:
        return "free", MODEL_FREE, None, None
    billing = get_user_billing(user["id"])
    if billing and billing.get("plan_id") == "pro" and billing.get("status") == "active":
        return "pro", MODEL_PRO, None, None
    used = get_usage_count(user["id"], current_period())
    return "free", MODEL_FREE, used, FREE_MATCH_LIMIT


# ---- Prompts (server-side) ------------------------------------------------------
ANALYSIS_SYS = """You are a precise, honest resume-to-JD fit analyzer for any role or industry.

Given a job description and a resume, produce a detailed fit analysis. Be honest — don't inflate scores.

Return ONLY valid JSON, no markdown, no prose, exactly this shape:
{
  "fit_score": <integer 0-100, realistic shortlisting odds weighting must-haves heavily>,
  "required": ["up to 12 key JD requirements that drive shortlisting"],
  "matched": ["requirements clearly evidenced in the resume"],
  "partial": ["requirements adjacent/transferable but not explicit"],
  "missing": ["requirements genuinely absent from the resume"],
  "gaps": [
    {
      "skill": "<gap name>",
      "importance": "<critical|high|medium>",
      "why": "<one sentence: why this matters for the role and what the JD says about it>"
    }
  ],
  "rewritten_bullets": [
    {
      "original": "<exact bullet from resume most relevant to this JD>",
      "rewritten": "<same bullet reworded to mirror JD terminology, staying 100% accurate>",
      "keywords_matched": ["<JD keyword used in rewrite>"]
    }
  ],
  "highlights": ["<3-5 specific strengths the candidate already has that are strong matches for this role>"],
  "to_gain": [{"skill": "<missing skill>", "how": "<concrete 1-sentence prep action>"}]
}

Rules:
- rewritten_bullets: pick the 4-6 most impactful bullets from the resume. Rewrite them to echo JD language without fabricating any skills, employers, metrics, or tools.
- highlights: be specific (quote relevant experience from the resume, not generic praise).
- gaps: only include items that are genuinely missing or weak. Rank by importance to this specific role.
- fit_score: 0-40 = unlikely fit, 41-65 = moderate, 66-80 = strong, 81-100 = excellent."""

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
    interval: str = "annual"

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
def billing_config(authorization: Optional[str] = Header(None)):
    configured_prices = {"pro": bool(STRIPE_PRICE_PRO_MONTHLY or STRIPE_PRICE_PRO_ANNUAL)}
    user = resolve_user(authorization)
    plan_id, _, used, limit = resolve_plan(user)
    plans = []
    for plan in PLAN_CATALOG:
        item = dict(plan)
        item["stripe_configured"] = plan["id"] == "free" or configured_prices.get(plan["id"], False)
        item["active"] = plan["id"] == plan_id
        plans.append(item)
    return {
        "mode": APP_MODE,
        # Quotas only bite once we can actually track usage server-side; otherwise
        # (local/dev without a Supabase service role key) stay unlimited like before.
        "free_access": APP_MODE == "free" and not supabase_admin_enabled(),
        "payments_enabled": payments_enabled(),
        "plans": plans,
        "current_plan": plan_id,
        "matches_used": used,
        "matches_limit": limit,
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
def create_checkout(b: CheckoutIn, authorization: Optional[str] = Header(None)):
    plan_id = b.plan_id.strip().lower()
    if plan_id == "free":
        return {"checkout_url": None, "message": "Free access is currently active."}
    interval = b.interval if b.interval in ("monthly", "annual") else "annual"
    price_id = price_id_for(plan_id, interval)
    if not STRIPE_SECRET_KEY or not price_id:
        return JSONResponse({
            "error": "Payments are not enabled yet. Configure STRIPE_SECRET_KEY and the Pro price ids to activate checkout."
        }, status_code=400)
    user = resolve_user(authorization)
    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=b.success_url,
            cancel_url=b.cancel_url,
            allow_promotion_codes=True,
            client_reference_id=user["id"] if user else None,
        )
        return {"checkout_url": session.url}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/billing/webhook")
async def billing_webhook(request: Request):
    if not STRIPE_SECRET_KEY or not STRIPE_WEBHOOK_SECRET:
        return JSONResponse({"error": "Webhook not configured."}, status_code=400)
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        import stripe
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        return JSONResponse({"error": f"Invalid webhook signature: {e}"}, status_code=400)

    etype = event["type"]
    obj = event["data"]["object"]

    if etype == "checkout.session.completed":
        user_id = obj.get("client_reference_id")
        if user_id:
            upsert_user_billing(
                user_id,
                plan_id="pro",
                status="active",
                stripe_customer_id=obj.get("customer"),
                stripe_subscription_id=obj.get("subscription"),
            )
    elif etype in ("customer.subscription.updated", "customer.subscription.deleted"):
        customer_id = obj.get("customer")
        status = "active" if obj.get("status") in ("active", "trialing") else "canceled"
        if supabase_admin_enabled() and customer_id:
            try:
                r = httpx.get(
                    f"{SUPABASE_URL}/rest/v1/user_billing",
                    params={"stripe_customer_id": f"eq.{customer_id}", "select": "user_id"},
                    headers=_supabase_admin_headers(),
                    timeout=8,
                )
                rows = r.json() if r.status_code == 200 else []
                if rows:
                    upsert_user_billing(rows[0]["user_id"], status=status, plan_id="pro" if status == "active" else "free")
            except Exception:
                pass
    return {"received": True}

@app.post("/api/analyze")
def analyze(b: AnalyzeIn, authorization: Optional[str] = Header(None)):
    import json, re
    account = resolve_user(authorization)
    plan_id, model, used, limit = resolve_plan(account)
    if account and plan_id == "free" and used is not None and limit is not None and used >= limit:
        return JSONResponse({
            "error": f"You've used all {limit} free resume matches this month. Upgrade to Pro for unlimited matches.",
            "upgrade_required": True,
        }, status_code=403)
    try:
        raw = run_llm(ANALYSIS_SYS, f"JOB DESCRIPTION:\n{b.jd}\n\nRESUME:\n{b.resume}", 2500, model=model)
        raw = re.sub(r"```json|```", "", raw).strip()
        data = json.loads(raw)
        # Backward-compat: older prompt used "score", new uses "fit_score"
        if "fit_score" not in data and "score" in data:
            data["fit_score"] = data["score"]
        if "score" not in data and "fit_score" in data:
            data["score"] = data["fit_score"]
        if account and plan_id == "free":
            increment_usage(account["id"], current_period())
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/tailor")
def tailor(b: TailorIn, authorization: Optional[str] = Header(None)):
    try:
        _, model, _, _ = resolve_plan(resolve_user(authorization))
        out = run_llm(RESUME_SYS,
            f"JOB DESCRIPTION:\n{b.jd}\n\nMASTER RESUME:\n{b.resume}\n\nEXTRA INSTRUCTIONS:\n{b.comments or '(none)'}", 2400, model=model)
        body, changes = out, ""
        if "===CHANGES===" in out:
            body, changes = out.split("===CHANGES===", 1)
        return {"resume": body.strip(), "changes": changes.strip()}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

@app.post("/api/cover")
def cover(b: CoverIn, authorization: Optional[str] = Header(None)):
    try:
        _, model, _, _ = resolve_plan(resolve_user(authorization))
        prompt = (f"JOB DESCRIPTION:\n{b.jd}\n\nCANDIDATE RESUME:\n{b.resume}\n\n"
                f"COMPANY: {b.company or '(see JD)'}\nROLE: {b.role or '(see JD)'}\n"
                f"EXTRA INSTRUCTIONS:\n{b.comments or '(none)'}")
        return {"letter": run_llm(COVER_SYS, prompt, 1200, model=model)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

@app.get("/", response_class=HTMLResponse)
def index():
    return Path(__file__).with_name("index.html").read_text(encoding="utf-8")
