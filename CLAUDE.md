# Resume_curator

FastAPI backend (`app.py`) serving a single static `index.html` — a resume-to-job-description
fit analyzer ("Resume→Fit"). No build step, no bundler: `index.html` is plain HTML/CSS/JS with
Tailwind loaded via CDN, and `app.py` is one file with all API routes.

## Frontend architecture (`index.html`)

- Single page, three top-level views toggled via `document.body.dataset.view` and a `hidden`
  class on `#authView` / `#appView` / `#upgradeView`: `setView('auth'|'app'|'upgrade')`.
- The design (colors, layout, copy, components) was ported from a set of Wonder
  (canvas design tool) artboards — dark theme, teal `#14b8a6` accent, Inter font. If asked to
  change visual design, check whether the user has newer Wonder artboards to pull from before
  hand-rolling new CSS.
- `appView` keeps the original app's tab system (`Analyze` / `Saved resumes` / `Settings`) via
  `setTab()` — these are NOT separate Wonder artboards, they were preserved from the prior
  version and just restyled.
- Element ids in the DOM are load-bearing — JS throughout (`renderAnalysis`, `runGenerate`,
  `loadHistory`, `loadBilling`, etc.) selects by id. Don't rename ids without updating every
  reference.

### `FORCE_DEMO_MODE` (temporary, currently `true`)

Near the top of the `<script>` block (search for `FORCE_DEMO_MODE`), `initSupabase()` short-circuits
into local/demo mode unconditionally, skipping real Supabase login regardless of what's configured
on the server. This was set at the user's request so the public Render demo stays open without
requiring sign-in, independent of whatever Supabase env vars exist on that deployment.

**Flip `FORCE_DEMO_MODE` to `false` when real auth should be required again** — everything else
(magic-link email via `signInWithOtp`, Google + GitHub OAuth, the `auth` view UI) is already wired
and will work as soon as this is turned off and Supabase env vars are set.

## Backend (`app.py`) — Pro plan enforcement

Real (not just cosmetic) quota + subscription logic was added:

- Free plan: 3 resume matches/month, tracked server-side. Pro plan: unlimited + a stronger model
  (`gpt-4o` vs `gpt-4o-mini`) — see `resolve_plan()`.
- Enforcement only activates if `SUPABASE_SERVICE_ROLE_KEY` + `SUPABASE_JWT_SECRET` are set
  (`supabase_admin_enabled()`). Without them (e.g. local dev, or Render until configured), the
  app behaves exactly as before: unlimited, no auth required.
- Stripe: two separate Price ids for Pro (`STRIPE_PRICE_PRO_MONTHLY` / `STRIPE_PRICE_PRO_ANNUAL`),
  a webhook at `/api/billing/webhook` (needs `STRIPE_WEBHOOK_SECRET`) that flips a user's plan in
  the new `user_billing` Supabase table on `checkout.session.completed` /
  `customer.subscription.updated|deleted`.
- All the new env vars are documented in `.env.example`. None of this is live on Render yet —
  it's built and ready, just not turned on (`FORCE_DEMO_MODE` also means nobody can trigger
  checkout as a signed-in user right now anyway, since there's no real signed-in user).

## Database (`supabase/schema.sql`)

Additive only — new `user_billing` and `usage_counters` tables (RLS: users can read their own row,
only the service-role key can write). If/when quota enforcement goes live, this file needs to be
run against the actual Supabase project (it is NOT auto-applied anywhere).

## Deployment

Render, auto-deploys from GitHub `main` on push (per user; no `render.yaml` in this repo, so
build/start commands live in the Render dashboard, presumably `pip install -r requirements.txt`
+ `uvicorn app:app --host 0.0.0.0 --port $PORT`). Two new Python deps were added
(`PyJWT`, `httpx`) — picked up automatically by the existing `pip install -r requirements.txt`
build step.
