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

## IMPORTANT: who pays for the API (read before sharing)

Every generation costs OpenAI API tokens. There are two modes:

1. **BYOK (recommended for public sharing).** Each user pastes their OWN OpenAI
   key in the field at the top. It is sent per-request and never stored on the
   server. Your wallet is safe. Downside: users need their own key.

2. **Host-pays.** You set `OPENAI_API_KEY` on the server; users leave the field
   blank and YOU pay for everyone. Only do this if you also:
   - set a monthly **spend limit** in the OpenAI dashboard (Settings -> Limits), and
   - restrict who can reach the URL (don't post a host-pays link publicly).

   A public host-pays link with no spend limit can be drained by strangers.

Get a key + set a spend limit at https://platform.openai.com

---

## Run locally
```bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
# host-pays (optional): export OPENAI_API_KEY=sk-...
uvicorn app:app --reload --port 8000
```
Open http://localhost:8000

## Deploy on Replit
1. Create a new Repl -> "Import" your files (or upload this folder).
2. If host-pays: open the **Secrets** tab (lock icon) and add
   `OPENAI_API_KEY = sk-...`. For BYOK, skip this.
3. Press **Run**. The webview shows the app.
4. To get a stable public link to share, click **Deploy** (Autoscale) — Replit
   gives you a `*.replit.app` URL. The included `.replit` sets the run command;
   if Replit asks, use:  `uvicorn app:app --host 0.0.0.0 --port $PORT`

## Deploy on Vercel
1. Push this folder to a GitHub repo.
2. On vercel.com -> **Add New Project** -> import the repo.
3. If host-pays: Project **Settings -> Environment Variables** ->
   add `OPENAI_API_KEY`. For BYOK, skip this.
4. **Deploy.** You get a `*.vercel.app` URL to share.
   (`vercel.json` tells Vercel to run `app.py` as a Python serverless function.)

Note: Vercel functions are stateless/ephemeral and have an execution time limit;
fine for this tool. The resume + key persist in each user's browser (localStorage).

## Changing the model
Edit `MODEL` in `app.py` (e.g. gpt-5.5 for higher quality, gpt-4o-mini to cut cost).

## Uploading a résumé or JD
Both the résumé and JD boxes have an **Upload PDF / TXT** button. PDFs are read in
the browser (via pdf.js from a CDN) and the extracted text drops into the editable
box — review and fix it before generating, since PDF extraction isn't perfect.
Scanned/image-only PDFs have no selectable text and won't extract (no OCR).
