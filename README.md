# JD -> Tailored Resume + Cover Letter

A small FastAPI app that tailors a resume to a job description and drafts a cover
letter. Model behind it: **gpt-4o-mini** (configurable in app.py).

Runs three ways: locally, on Replit, or on Vercel. Same files for all three.

## Files
- `app.py`      FastAPI backend (prompts + OpenAI calls)
- `index.html`  the UI (served by FastAPI)
- `requirements.txt`
- `vercel.json`, `.vercelignore`  Vercel config
- `.replit`     Replit run/deploy config

---

## IMPORTANT: OpenAI API key

The OpenAI key is server-side only. Users never paste or see API keys in the UI.
Set this in `.env` locally and in your hosting provider's environment variables
for production:

```bash
OPENAI_API_KEY=sk-...
```

Because you pay for all generations, keep the app behind authentication and set
a monthly spend limit in the OpenAI dashboard. Before charging users, add usage
limits tied to Supabase user ids and your future billing plan.

---

## Run locally
```bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
# required: add OPENAI_API_KEY=sk-... to .env
uvicorn app:app --reload --port 8000
```
Open http://localhost:8000

## Deploy on Replit
1. Create a new Repl -> "Import" your files (or upload this folder).
2. Open the **Secrets** tab (lock icon) and add `OPENAI_API_KEY = sk-...`.
3. Press **Run**. The webview shows the app.
4. To get a stable public link to share, click **Deploy** (Autoscale) — Replit
   gives you a `*.replit.app` URL. The included `.replit` sets the run command;
   if Replit asks, use:  `uvicorn app:app --host 0.0.0.0 --port $PORT`

## Deploy on Vercel
1. Push this folder to a GitHub repo.
2. On vercel.com -> **Add New Project** -> import the repo.
3. Project **Settings -> Environment Variables** -> add `OPENAI_API_KEY`.
4. **Deploy.** You get a `*.vercel.app` URL to share.
   (`vercel.json` tells Vercel to run `app.py` as a Python serverless function.)

Note: Vercel functions are stateless/ephemeral and have an execution time limit;
fine for this tool. The resume + key persist in each user's browser (localStorage).

## Changing the model
Edit `MODEL` in `app.py` (e.g. gpt-5.5 for higher quality, gpt-4o-mini to cut cost).

## Billing mode
The app is currently set up for **free beta access**. Billing is scaffolded but
does not block resume generation.

Default behavior:
- `APP_MODE=free`
- `/api/billing/config` returns the visible plan catalog for the UI.
- `/api/billing/checkout` stays inactive until Stripe credentials are configured.

To enable Stripe checkout later, set these environment variables:
```bash
APP_MODE=paid
STRIPE_SECRET_KEY=sk_live_or_test_...
STRIPE_PRICE_STARTER=price_...
STRIPE_PRICE_PRO=price_...
```

The current checkout endpoint creates Stripe subscription Checkout sessions for
the `starter` and `pro` plan ids. Usage limits and payment gates should be added
after auth and saved resume history are in place.

## Supabase auth + saved resumes
The UI can use Supabase Auth and store generated resume history when these env
vars are configured:

```bash
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_ANON_KEY=your_anon_public_key
```

Local setup:
1. Copy `.env.example` to `.env`.
2. Fill in `SUPABASE_URL` and `SUPABASE_ANON_KEY`.
3. In Supabase, open **SQL Editor** and run `supabase/schema.sql`.
4. Restart the FastAPI server.

Production setup:
- Add the same `SUPABASE_URL` and `SUPABASE_ANON_KEY` values in your hosting
  provider's environment variables.
- Keep the Supabase `service_role` key out of frontend code. It is not needed
  for the current auth/history flow.
- The `resume_generations` table uses Row Level Security so users can only read
  and write their own saved resumes.

Google login:
1. In Supabase, open **Authentication -> Sign In / Providers**.
2. Enable **Google**.
3. Add the Google OAuth client id/secret from Google Cloud Console.
4. Add your app URL under Supabase **Authentication -> URL Configuration**:
   - Local: `http://localhost:8000`
   - Production: your deployed app URL
5. In Google Cloud OAuth settings, add Supabase's callback URL shown on the
   Google provider page.

## PDF export templates
Generated resumes can be exported as PDFs through `/api/export/pdf`.

Available template ids:
- `classic` - ATS-friendly one-column resume
- `modern` - clean accent layout
- `technical` - compact engineering-focused layout
- `academic` - research/publication-friendly layout
- `executive` - polished senior profile layout

The backend uses ReportLab so exports work without a LaTeX installation.

## Uploading a résumé or JD
Both the résumé and JD boxes have an **Upload PDF / TXT** button. PDFs are read in
the browser (via pdf.js from a CDN) and the extracted text drops into the editable
box — review and fix it before generating, since PDF extraction isn't perfect.
Scanned/image-only PDFs have no selectable text and won't extract (no OCR).
