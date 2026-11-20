-- =============================================================
-- SCRUM-38: Core Data Model Migration
-- ProfessorDM / Sweetlife Flora Knowledge App
-- Run this in Supabase SQL Editor (Project > SQL Editor > New Query)
-- =============================================================

-- Enable required extensions
create extension if not exists "uuid-ossp";
create extension if not exists "vector";

-- =============================================================
-- SECTION 1: Identity & Auth Layer
-- =============================================================

create table if not exists profiles (
  id            uuid primary key references auth.users(id) on delete cascade,
  role          text not null check (role in ('creator', 'admin', 'consumer')),
  display_name  text,
  created_at    timestamptz not null default now()
);

create table if not exists creators (
  id          uuid primary key default uuid_generate_v4(),
  profile_id  uuid not null references profiles(id) on delete cascade,
  brand_name  text,
  status      text not null default 'setup' check (status in ('setup', 'active'))
);

create table if not exists consumers (
  id                  uuid primary key default uuid_generate_v4(),
  profile_id          uuid not null references profiles(id) on delete cascade,
  free_views_used     int not null default 0,
  auth_provider       text check (auth_provider in ('email', 'google', 'apple', 'azure')),
  stripe_customer_id  text
);

-- =============================================================
-- SECTION 2: Creator Configuration
-- =============================================================

create table if not exists creator_settings (
  creator_id                      uuid primary key references creators(id) on delete cascade,
  question_price_cents            int not null default 500,
  platform_fee_bps                int not null default 1500,
  followups_included              int not null default 3,
  knowledge_app_enabled           bool not null default false,
  kb_subscription_price_cents     int not null default 1000,
  free_answer_limit               int not null default 5,
  subscriber_question_price_cents int not null default 250,
  expected_answer_time            text,
  payout_method                   text,
  payout_mode                     text default 'automatic'
);

-- =============================================================
-- SECTION 3: Instagram Integration
-- =============================================================

create table if not exists ig_accounts (
  id                    uuid primary key default uuid_generate_v4(),
  creator_id            uuid not null references creators(id) on delete cascade,
  ig_user_id            text not null unique,
  vault_token_id        uuid,
  token_expires_at      timestamptz,
  human_agent_approved  bool not null default false
);

create table if not exists ig_followers (
  id              uuid primary key default uuid_generate_v4(),
  creator_id      uuid not null references creators(id) on delete cascade,
  ig_scoped_id    text not null unique,
  username        text,
  email           text,
  last_inbound_at timestamptz
);

-- =============================================================
-- SECTION 4: Messaging Pipeline
-- =============================================================

create table if not exists inbound_messages (
  id                uuid primary key default uuid_generate_v4(),
  follower_id       uuid not null references ig_followers(id),
  mid               text not null unique,
  text              text,
  category          text,
  confidence        numeric,
  override_category text,
  status            text,
  prompt_version    text,
  received_at       timestamptz not null default now()
);

create table if not exists clarification_rounds (
  id          uuid primary key default uuid_generate_v4(),
  message_id  uuid not null references inbound_messages(id) on delete cascade,
  round       int not null check (round between 1 and 2),
  prompt      text,
  reply       text
);

create table if not exists outbound_messages (
  id              uuid primary key default uuid_generate_v4(),
  draft_id        uuid,
  type            text not null check (type in (
                    'ask_link','clarification','confirmation',
                    'answer','followup','rating_prompt','survey','decline'
                  )),
  delivery_mode   text check (delivery_mode in ('standard','human_agent','fallback_email')),
  meta_message_id text,
  status          text,
  attempts        int not null default 0
);

-- =============================================================
-- SECTION 5: Questions & Answers
-- =============================================================

create table if not exists questions (
  id                  uuid primary key default uuid_generate_v4(),
  creator_id          uuid not null references creators(id),
  source              text not null check (source in ('instagram','knowledge_app')),
  follower_id         uuid references ig_followers(id),
  consumer_id         uuid references consumers(id),
  origin_message_id   uuid references inbound_messages(id),
  question_text       text not null,
  status              text not null,
  safety_flagged      bool not null default false,
  ask_token           text unique,
  price_cents         int,
  followups_included  int,
  followups_used      int not null default 0,
  paid_at             timestamptz,
  delivered_at        timestamptz,
  hold_ends_at        timestamptz,
  survey_sent_at      timestamptz,
  accepted_at         timestamptz
);

create table if not exists drafts (
  id              uuid primary key default uuid_generate_v4(),
  question_id     uuid not null references questions(id) on delete cascade,
  followup_id     uuid,
  ai_text         text,
  citations       jsonb,
  used_web_search bool not null default false,
  model_used      text,
  prompt_version  text,
  final_text      text,
  edit_distance   int,
  status          text,
  approved_at     timestamptz
);

create table if not exists followups (
  id          uuid primary key default uuid_generate_v4(),
  question_id uuid not null references questions(id) on delete cascade,
  seq         int not null,
  text        text,
  on_topic    bool,
  status      text
);

-- =============================================================
-- SECTION 6: Knowledge Base
-- =============================================================

create table if not exists knowledge_docs (
  id            uuid primary key default uuid_generate_v4(),
  creator_id    uuid not null references creators(id) on delete cascade,
  title         text,
  storage_path  text
);

create table if not exists knowledge_entries (
  id              uuid primary key default uuid_generate_v4(),
  creator_id      uuid not null references creators(id) on delete cascade,
  doc_id          uuid references knowledge_docs(id),
  question_id     uuid references questions(id),
  source          text not null check (source in ('question','doc','manual_fact')),
  content         text,
  voice_media_id  uuid,
  tags            text[],
  published       bool not null default false,
  embedding       vector(1536)
);

create table if not exists tags (
  id          uuid primary key default uuid_generate_v4(),
  creator_id  uuid not null references creators(id) on delete cascade,
  name        text not null
);

create table if not exists question_tags (
  question_id uuid not null references questions(id) on delete cascade,
  tag_id      uuid not null references tags(id) on delete cascade,
  primary key (question_id, tag_id)
);

-- =============================================================
-- SECTION 7: Media
-- =============================================================

create table if not exists media (
  id            uuid primary key default uuid_generate_v4(),
  question_id   uuid references questions(id),
  message_id    uuid references inbound_messages(id),
  storage_path  text,
  kind          text check (kind in ('image','voice_note'))
);

-- deferred FKs now that all tables exist
alter table knowledge_entries
  add constraint knowledge_entries_voice_media_id_fkey
  foreign key (voice_media_id) references media(id);

alter table outbound_messages
  add constraint outbound_messages_draft_id_fkey
  foreign key (draft_id) references drafts(id);

alter table drafts
  add constraint drafts_followup_id_fkey
  foreign key (followup_id) references followups(id);

-- =============================================================
-- SECTION 8: Payments & Billing
-- =============================================================

create table if not exists subscriptions (
  id                      uuid primary key default uuid_generate_v4(),
  consumer_id             uuid not null references consumers(id),
  stripe_subscription_id  text not null unique,
  status                  text,
  current_period_end      timestamptz,
  discount_spent_cents    int not null default 0
);

create table if not exists payments (
  id                        uuid primary key default uuid_generate_v4(),
  question_id               uuid not null references questions(id),
  stripe_payment_intent_id  text not null unique,
  amount_cents              int,
  platform_fee_cents        int,
  creator_share_cents       int,
  status                    text check (status in ('succeeded','refunded'))
);

create table if not exists payouts (
  id            uuid primary key default uuid_generate_v4(),
  creator_id    uuid not null references creators(id),
  amount_cents  int,
  trigger       text check (trigger in ('manual','weekly_auto','30_day_auto')),
  status        text check (status in ('requested','paid')),
  reference     text
);

create table if not exists ledger_entries (
  id                uuid primary key default uuid_generate_v4(),
  entry_type        text not null check (entry_type in (
                      'question_fee','platform_fee','refund','subscription','payout'
                    )),
  amount_cents      int not null,
  payment_id        uuid references payments(id),
  subscription_id   uuid references subscriptions(id),
  payout_id         uuid references payouts(id),
  created_at        timestamptz not null default now()
);

create table if not exists ratings (
  id          uuid primary key default uuid_generate_v4(),
  question_id uuid not null unique references questions(id),
  stars       int not null check (stars between 1 and 5),
  review      text,
  created_at  timestamptz not null default now()
);

create table if not exists refund_requests (
  id          uuid primary key default uuid_generate_v4(),
  question_id uuid not null references questions(id),
  reason      text,
  status      text not null default 'pending' check (status in ('pending','approved','denied','revisited')),
  decided_by  uuid references profiles(id)
);

-- =============================================================
-- SECTION 9: Trust & Safety
-- =============================================================

create table if not exists safety_flags (
  id          uuid primary key default uuid_generate_v4(),
  target_type text not null check (target_type in ('message','draft','final','knowledge_entry')),
  target_id   uuid not null,
  checkpoint  text check (checkpoint in ('1','2','3')),
  layer       text check (layer in ('moderation','rules','policy')),
  category    text,
  status      text not null default 'open' check (status in ('open','creator_reviewed','approved','sent_back')),
  feedback    text,
  reviewed_by uuid references profiles(id)
);

-- =============================================================
-- SECTION 10: Analytics & Audit
-- =============================================================

create table if not exists events (
  id          uuid primary key default uuid_generate_v4(),
  name        text not null,
  props       jsonb,
  created_at  timestamptz not null default now()
);

create table if not exists audit_log (
  id            uuid primary key default uuid_generate_v4(),
  actor_id      uuid references profiles(id),
  action        text not null,
  entity        text not null,
  entity_id     uuid,
  before_after  jsonb,
  created_at    timestamptz not null default now()
);

-- =============================================================
-- SECTION 11: Indexes
-- =============================================================

create index if not exists idx_questions_creator_id      on questions(creator_id);
create index if not exists idx_questions_status          on questions(status);
create index if not exists idx_inbound_messages_follower on inbound_messages(follower_id);
create index if not exists idx_ig_followers_creator_id   on ig_followers(creator_id);
create index if not exists idx_knowledge_entries_creator on knowledge_entries(creator_id);
create index if not exists idx_drafts_question_id        on drafts(question_id);
create index if not exists idx_payments_question_id      on payments(question_id);
create index if not exists idx_ledger_entries_type       on ledger_entries(entry_type);
create index if not exists idx_safety_flags_target       on safety_flags(target_id, target_type);
create index if not exists idx_audit_log_entity          on audit_log(entity, entity_id);

create index if not exists idx_knowledge_entries_embedding
  on knowledge_entries using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);