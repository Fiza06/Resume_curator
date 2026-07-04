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
