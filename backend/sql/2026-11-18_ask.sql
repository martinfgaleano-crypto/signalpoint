-- "Ask about any event": one row per answered question, used only for the daily limit.
-- No policies: only the edge function (service role) reads or writes it.
create table if not exists public.ask_log (
  id bigserial primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  brief_id text,
  created_at timestamptz not null default now()
);
create index if not exists ask_log_user_day on public.ask_log (user_id, created_at);
alter table public.ask_log enable row level security;
