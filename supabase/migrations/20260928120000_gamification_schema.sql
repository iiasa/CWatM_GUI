-- CWatM GUI gamification - schema (step S1).
--
-- Tables:
--   profiles       one row per auth user (username + optional name/country/institute)
--   game_config    tunable rules (points per run, minimum timesteps, daily cap, ...)
--   badges         the river ladder (Breg ... Amazonas) with point thresholds
--   point_events   every point ever awarded; written ONLY by security-definer functions
--   user_badges    badges a user has earned
--   login_attempts failed username logins, for the login-with-username throttle
--
-- Security model: row level security on every table. A client (the GUI, holding the
-- public anon/publishable key + the user's JWT) can read its own rows and edit a few
-- profile columns - nothing else. Points are awarded server-side by award_run(),
-- which decides the number of points itself.

-- ---------------------------------------------------------------------------
-- profiles
-- ---------------------------------------------------------------------------
create table public.profiles (
    id                  uuid primary key references auth.users (id) on delete cascade,
    -- 3-30 chars, starts alphanumeric, no '@' - so the client can tell a username
    -- from an email address by the '@' alone.
    username            text not null
                        check (username ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{2,29}$'),
    full_name           text check (char_length(full_name) <= 100),
    country             text check (char_length(country) <= 60),
    institute           text check (char_length(institute) <= 150),
    show_on_leaderboard boolean not null default false,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

-- Usernames are unique case-insensitively ("Peter" and "peter" are the same user).
create unique index profiles_username_lower_key on public.profiles (lower(username));

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at := now();
    return new;
end
$$;

create trigger profiles_touch_updated_at
    before update on public.profiles
    for each row execute function public.touch_updated_at();

-- The profile is created from the sign-up metadata (supabase auth.sign_up
-- options.data = {username, full_name, country, institute}). A missing/invalid or
-- taken username makes the whole sign-up fail, so no auth user exists without a
-- profile. The client checks username_available() first to give a readable message.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    md jsonb := coalesce(new.raw_user_meta_data, '{}'::jsonb);
begin
    insert into public.profiles (id, username, full_name, country, institute)
    values (new.id,
            btrim(md ->> 'username'),
            nullif(btrim(md ->> 'full_name'), ''),
            nullif(btrim(md ->> 'country'), ''),
            nullif(btrim(md ->> 'institute'), ''));
    return new;
end
$$;

create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------------
-- game_config
-- ---------------------------------------------------------------------------
create table public.game_config (
    key         text primary key,
    value       jsonb not null,
    description text
);

-- ---------------------------------------------------------------------------
-- badges
-- ---------------------------------------------------------------------------
create table public.badges (
    code            text primary key check (code ~ '^[a-z0-9_]{2,40}$'),
    name            text not null,
    river_length_km integer check (river_length_km > 0),
    points_required integer not null unique check (points_required >= 0),
    sort_order      integer not null unique,
    description     text
);

-- ---------------------------------------------------------------------------
-- point_events
-- ---------------------------------------------------------------------------
create table public.point_events (
    id         bigint generated always as identity primary key,
    user_id    uuid not null references auth.users (id) on delete cascade,
    -- run = a full CWatM run; training = a finished training (later); bonus = manual.
    source     text not null check (source in ('run', 'training', 'bonus')),
    -- run: the Journal-of-Runs uid (uuid4 hex); training: the training id.
    source_ref text not null check (char_length(source_ref) between 1 and 100),
    points     integer not null check (points between 0 and 1000),
    -- Non-identifying facts only (gui_version, kind, timesteps, duration_s) -
    -- never paths or settings content. Built server-side, see award_run().
    meta       jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (user_id, source, source_ref)
);

create index point_events_user_created_idx on public.point_events (user_id, created_at);

-- ---------------------------------------------------------------------------
-- user_badges
-- ---------------------------------------------------------------------------
create table public.user_badges (
    user_id    uuid not null references auth.users (id) on delete cascade,
    badge_code text not null references public.badges (code) on update cascade,
    awarded_at timestamptz not null default now(),
    primary key (user_id, badge_code)
);

-- ---------------------------------------------------------------------------
-- login_attempts (service role only)
-- ---------------------------------------------------------------------------
create table public.login_attempts (
    id           bigint generated always as identity primary key,
    username     text not null,
    attempted_at timestamptz not null default now()
);

create index login_attempts_username_idx
    on public.login_attempts (lower(username), attempted_at);

-- ---------------------------------------------------------------------------
-- Row level security + grants
-- ---------------------------------------------------------------------------
-- Supabase grants everything on new public tables to anon/authenticated by default;
-- start from nothing and grant exactly what is needed.
revoke all on table public.profiles, public.game_config, public.badges,
                    public.point_events, public.user_badges, public.login_attempts
    from anon, authenticated;

alter table public.profiles       enable row level security;
alter table public.game_config    enable row level security;
alter table public.badges         enable row level security;
alter table public.point_events   enable row level security;
alter table public.user_badges    enable row level security;
alter table public.login_attempts enable row level security;   -- no policies: service role only

-- profiles: read + edit your own row; id/created_at/updated_at are not editable.
grant select on public.profiles to authenticated;
grant update (username, full_name, country, institute, show_on_leaderboard)
    on public.profiles to authenticated;

create policy "profiles: read own" on public.profiles
    for select to authenticated
    using ((select auth.uid()) = id);

create policy "profiles: update own" on public.profiles
    for update to authenticated
    using ((select auth.uid()) = id)
    with check ((select auth.uid()) = id);

-- game rules and the badge ladder are public.
grant select on public.game_config to anon, authenticated;
grant select on public.badges      to anon, authenticated;

create policy "game_config: read all" on public.game_config
    for select to anon, authenticated using (true);

create policy "badges: read all" on public.badges
    for select to anon, authenticated using (true);

-- points and badges: read your own; no insert/update/delete policy at all, so
-- only the security-definer functions can write them.
grant select on public.point_events to authenticated;
grant select on public.user_badges  to authenticated;

create policy "point_events: read own" on public.point_events
    for select to authenticated
    using ((select auth.uid()) = user_id);

create policy "user_badges: read own" on public.user_badges
    for select to authenticated
    using ((select auth.uid()) = user_id);
