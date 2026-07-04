-- Run this in Supabase SQL Editor for the resume app project.
-- It stores each user's generated resume history and protects rows with RLS.

create extension if not exists pgcrypto;

create table if not exists public.resume_generations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null default 'Saved resume',
  mode text not null default 'tailor',
  company text,
  role text,
  source_resume text,
  job_description text,
  tailored_resume text not null,
  cover_letter text,
  changes text,
  analysis jsonb,
  comments text,
  template_id text default 'plain_text',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists resume_generations_user_created_idx
  on public.resume_generations (user_id, created_at desc);

alter table public.resume_generations enable row level security;

drop policy if exists "Users can read their own resume generations" on public.resume_generations;
create policy "Users can read their own resume generations"
  on public.resume_generations
  for select
  using (auth.uid() = user_id);

drop policy if exists "Users can insert their own resume generations" on public.resume_generations;
create policy "Users can insert their own resume generations"
  on public.resume_generations
  for insert
  with check (auth.uid() = user_id);

drop policy if exists "Users can update their own resume generations" on public.resume_generations;
create policy "Users can update their own resume generations"
  on public.resume_generations
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists "Users can delete their own resume generations" on public.resume_generations;
create policy "Users can delete their own resume generations"
  on public.resume_generations
  for delete
  using (auth.uid() = user_id);

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists touch_resume_generations_updated_at on public.resume_generations;
create trigger touch_resume_generations_updated_at
  before update on public.resume_generations
  for each row
  execute function public.touch_updated_at();

-- Pro plan / subscription state, written only by the server (service-role key)
-- from the Stripe webhook. Users can read their own row to show plan status.
create table if not exists public.user_billing (
  user_id uuid primary key references auth.users(id) on delete cascade,
  plan_id text not null default 'free',
  status text not null default 'inactive',
  stripe_customer_id text,
  stripe_subscription_id text,
  current_period_end timestamptz,
  updated_at timestamptz not null default now()
);

alter table public.user_billing enable row level security;

drop policy if exists "Users can read their own billing row" on public.user_billing;
create policy "Users can read their own billing row"
  on public.user_billing
  for select
  using (auth.uid() = user_id);
-- No insert/update/delete policies for authenticated users: only the
-- service-role key (which bypasses RLS) may write this table, from app.py's
-- Stripe webhook handler.

drop trigger if exists touch_user_billing_updated_at on public.user_billing;
create trigger touch_user_billing_updated_at
  before update on public.user_billing
  for each row
  execute function public.touch_updated_at();

-- Monthly free-tier usage counters, keyed by calendar period ("YYYY-MM").
-- Incremented atomically via the increment_usage() function below, called by
-- app.py with the service-role key after a successful /api/analyze call.
create table if not exists public.usage_counters (
  user_id uuid not null references auth.users(id) on delete cascade,
  period text not null,
  match_count int not null default 0,
  updated_at timestamptz not null default now(),
  primary key (user_id, period)
);

alter table public.usage_counters enable row level security;

drop policy if exists "Users can read their own usage" on public.usage_counters;
create policy "Users can read their own usage"
  on public.usage_counters
  for select
  using (auth.uid() = user_id);
-- No insert/update policy for authenticated users: counts are only mutated
-- via increment_usage(), a SECURITY DEFINER function called with the
-- service-role key.

create or replace function public.increment_usage(p_user_id uuid, p_period text)
returns int
language plpgsql
security definer
set search_path = public
as $$
declare
  new_count int;
begin
  insert into public.usage_counters (user_id, period, match_count)
  values (p_user_id, p_period, 1)
  on conflict (user_id, period)
  do update set match_count = usage_counters.match_count + 1, updated_at = now()
  returning match_count into new_count;
  return new_count;
end;
$$;
