-- Opportunity Scout — Supabase schema v2
-- Run in Supabase SQL editor. Idempotent where possible.
-- v2 changes for review:
-- - RLS enabled with NO anon policies (service_role only, docs say it bypasses RLS)
-- - nigeria_eligibility: eligible/excluded/unclear (replaces boolean where possible)
-- - ai_queue + ai_usage for persistent rate limiting
-- - heartbeat, run_logs, etc.

create extension if not exists "pgcrypto";

-- ── Profiles ──
create table if not exists profiles (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  email text unique,
  course text,
  academic_year text,
  expected_graduation date,
  cgpa numeric,
  cgpa_scale numeric,
  research_experience text,
  projects text,
  publications text,
  lab_skills text[],
  target_levels text[],
  preferred_countries text[],
  target_start_date date,
  languages text[],
  primary_field text default 'Physiology',
  other_fields text[],
  funding_need text check (funding_need in ('fully_funded_only','partly_funded_ok','self_funded_ok')) default 'fully_funded_only',
  upfront_budget_usd numeric,
  ielts_status text,
  toefl_status text,
  referees_available int default 0,
  documents jsonb default '{}',
  cv_text text,
  strong_threshold int default 70,
  receive_possible bool default true,
  summary_time text default '19:00',
  quiet_hours_start text default '22:00',
  quiet_hours_end text default '06:00',
  last_login timestamptz
);

-- ── Opportunities ──
create table if not exists opportunities (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  title text not null,
  funder text,
  host text,
  country text,
  level text,
  field text,
  field_category text check (field_category in ('primary','other')) default 'primary',
  funding_type text check (funding_type in ('full','partial','none','unknown')) default 'unknown',
  funding_covers jsonb default '{}',
  eligibility text,
  -- v2: three-state Nigeria eligibility
  nigeria_eligibility text check (nigeria_eligibility in ('eligible','excluded','unclear')) default 'unclear',
  nigeria_eligible bool, -- deprecated, kept for backward compat; prefer nigeria_eligibility
  min_grade text,
  opening_date date,
  deadline timestamptz,
  deadline_tz text,
  deadline_status text check (deadline_status in ('dated','rolling','unknown')) default 'dated',
  intake_year int, -- extracted from deadline/opening for dedup (e.g., 2027)
  required_docs jsonb default '[]',
  application_steps text,
  cost_breakdown jsonb default '{}',
  cost_total_to_start numeric,
  cost_total_to_complete numeric,
  official_link text not null,
  source_id text not null,
  source_url text,
  trust_label text check (trust_label in ('VERIFIED','UNVERIFIED','SUSPICIOUS')) default 'UNVERIFIED',
  trust_reasons jsonb default '[]',
  match_score int check (match_score between 0 and 100),
  match_reasons text,
  gap_list jsonb default '[]',
  dedup_hash text unique not null,
  content_hash text,
  raw_content text,
  status text check (status in ('new','seen','saved','dismissed','applied','expired')) default 'new',
  is_test boolean default false
);
create index if not exists idx_opp_deadline on opportunities(deadline);
create index if not exists idx_opp_trust on opportunities(trust_label);
create index if not exists idx_opp_score on opportunities(match_score desc);
create index if not exists idx_opp_field_cat on opportunities(field_category);
create index if not exists idx_opp_source on opportunities(source_id);
create index if not exists idx_opp_status on opportunities(status);
create index if not exists idx_opp_intake on opportunities(intake_year);
create index if not exists idx_opp_nigeria on opportunities(nigeria_eligibility);

-- Add new columns if table already existed (migrations)
do $$ begin
  if not exists (select 1 from information_schema.columns where table_name='opportunities' and column_name='nigeria_eligibility') then
    alter table opportunities add column nigeria_eligibility text check (nigeria_eligibility in ('eligible','excluded','unclear')) default 'unclear';
  end if;
  if not exists (select 1 from information_schema.columns where table_name='opportunities' and column_name='deadline_status') then
    alter table opportunities add column deadline_status text check (deadline_status in ('dated','rolling','unknown')) default 'dated';
  end if;
  if not exists (select 1 from information_schema.columns where table_name='opportunities' and column_name='intake_year') then
    alter table opportunities add column intake_year int;
  end if;
end $$;

-- ── User actions ──
create table if not exists user_actions (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid references profiles(id) on delete cascade,
  opportunity_id uuid references opportunities(id) on delete cascade,
  action text check (action in ('save','dismiss','apply','unsave')) not null,
  created_at timestamptz default now(),
  notes text
);
create index if not exists idx_actions_opp on user_actions(opportunity_id);

-- ── Sources health ──
create table if not exists sources (
  id text primary key,
  name text not null,
  type text,
  url text,
  rss text,
  enabled boolean default true,
  interval_minutes int,
  last_checked timestamptz,
  last_success timestamptz,
  last_error text,
  consecutive_failures int default 0,
  total_found int default 0,
  robots_txt_ok boolean,
  terms_ok boolean
);

-- ── Run logs ──
create table if not exists run_logs (
  id uuid primary key default gen_random_uuid(),
  started_at timestamptz default now(),
  finished_at timestamptz,
  status text check (status in ('running','success','partial','failed')) default 'running',
  sources_checked int default 0,
  new_opportunities int default 0,
  updated_opportunities int default 0,
  errors jsonb default '[]',
  ai_calls int default 0,
  ai_queued int default 0,
  duration_seconds numeric
);

-- ── Alerts log ──
create table if not exists alerts_sent (
  id uuid primary key default gen_random_uuid(),
  opportunity_id uuid references opportunities(id) on delete cascade,
  alert_type text check (alert_type in ('strong_immediate','possible_digest','deadline_reminder','system_alert')) not null,
  channel text check (channel in ('email','telegram','both')) not null,
  sent_at timestamptz default now(),
  dedup_key text unique not null
);

-- ── Heartbeat ──
create table if not exists heartbeat (
  id int primary key default 1,
  last_run timestamptz default now(),
  last_success timestamptz,
  last_heartbeat_commit date,
  worker_version text,
  check (id = 1)
);
insert into heartbeat (id) values (1) on conflict (id) do nothing;

-- ── AI Queue (persistent, replaces /tmp file) ──
create table if not exists ai_queue (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz default now(),
  source_id text not null,
  url text not null,
  title text,
  page_text text,
  attempts int default 0,
  status text check (status in ('pending','processing','done','failed')) default 'pending',
  last_error text,
  dedup_hash text
);
create index if not exists idx_queue_status on ai_queue(status, created_at);

-- ── AI Usage counters (persistent RPM/RPD) ──
create table if not exists ai_usage (
  id uuid primary key default gen_random_uuid(),
  window_start timestamptz not null,
  window_type text check (window_type in ('minute','day')) not null,
  count int default 0,
  unique(window_start, window_type)
);
create index if not exists idx_ai_usage_window on ai_usage(window_start, window_type);

-- Updated_at trigger
create or replace function touch_updated_at() returns trigger as $$
begin new.updated_at = now(); return new; end; $$ language plpgsql;
drop trigger if exists trg_profiles_updated on profiles;
create trigger trg_profiles_updated before update on profiles for each row execute function touch_updated_at();
drop trigger if exists trg_opps_updated on opportunities;
create trigger trg_opps_updated before update on opportunities for each row execute function touch_updated_at();

-- ── RLS: enable with NO anon policies ──
-- Service_role bypasses RLS, so worker/dashboard using service key works.
-- Anon (and any other role) has no policies → cannot read/write.
alter table profiles enable row level security;
alter table opportunities enable row level security;
alter table user_actions enable row level security;
alter table sources enable row level security;
alter table run_logs enable row level security;
alter table alerts_sent enable row level security;
alter table heartbeat enable row level security;
alter table ai_queue enable row level security;
alter table ai_usage enable row level security;

-- Drop old permissive policies if they exist (from v1)
do $$ declare r record; begin
  for r in select polname from pg_policy where polname='allow_all_anon' loop
    execute format('drop policy if exists %I on profiles', r.polname);
    execute format('drop policy if exists %I on opportunities', r.polname);
    execute format('drop policy if exists %I on user_actions', r.polname);
    execute format('drop policy if exists %I on sources', r.polname);
    execute format('drop policy if exists %I on run_logs', r.polname);
    execute format('drop policy if exists %I on alerts_sent', r.polname);
    execute format('drop policy if exists %I on heartbeat', r.polname);
  end loop;
end $$;

-- No anon policies created. Service_role bypasses RLS.
-- If you need fine-grained user access later, add Supabase Auth policies here.
