-- Phase 1 Supabase schema for the BYOK AI Agent app.
-- Run this in the Supabase SQL editor (or via `supabase db push`).

-- Enable UUID generation (Supabase projects usually already have this).
create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- users
-- Mirrors/extends auth.users with app-specific profile fields.
-- ---------------------------------------------------------------------------
create table if not exists public.users (
    id uuid primary key default gen_random_uuid() references auth.users (id) on delete cascade,
    email text not null unique,
    codeforces_handle text,
    created_at timestamptz not null default now()
);

alter table public.users enable row level security;

create policy "Users can view their own row"
    on public.users for select
    using (auth.uid() = id);

create policy "Users can update their own row"
    on public.users for update
    using (auth.uid() = id);

-- ---------------------------------------------------------------------------
-- api_keys
-- BYOK: each user's own LLM provider API key(s), scoped per-user.
-- ---------------------------------------------------------------------------
create table if not exists public.api_keys (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.users (id) on delete cascade,
    provider text not null, -- e.g. 'openai', 'anthropic', 'google'
    encrypted_key text not null, -- store encrypted at rest, never plaintext
    created_at timestamptz not null default now()
);

alter table public.api_keys enable row level security;

create policy "Users can manage their own api keys"
    on public.api_keys for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

create index if not exists api_keys_user_id_idx on public.api_keys (user_id);
