-- Morning digest: who wants it, in which language, for which markets. Each user sees and changes only their own row.
create table if not exists public.digest_subs (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  lang text not null default 'es' check (lang in ('es','en')),
  watch text[] not null default '{}',
  enabled boolean not null default true,
  last_sent date,
  updated_at timestamptz not null default now()
);
alter table public.digest_subs enable row level security;
create policy "digest own select" on public.digest_subs for select using (auth.uid() = user_id);
create policy "digest own insert" on public.digest_subs for insert with check (auth.uid() = user_id);
create policy "digest own update" on public.digest_subs for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
