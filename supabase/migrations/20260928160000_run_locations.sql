-- CWatM GUI - anonymous run locations (where CWatM is run, and how often).
--
-- A logged-in user who agreed (profiles.share_locations) reports the FIRST gauge
-- (lon/lat) of every successful run. What is stored is deliberately unlinkable:
--   * run_locations has NO user column, and is written by its own call - never
--     together with award_run, so the two requests are not joined server-side;
--   * it holds COUNTS per (rounded location, month), not one row per run, so the
--     time of a location cannot be matched against the time of a points row;
--   * coordinates are rounded to 0.01 degree (~1 km).
-- A per-user daily quota (user + day + number, never a location) stops flooding.
-- Anonymous counts cannot be exported or deleted per user - nothing links them to
-- anyone; the privacy notice says so.

-- ---------------------------------------------------------------------------
-- consent
-- ---------------------------------------------------------------------------
alter table public.profiles
    add column share_locations    boolean not null default false,
    add column share_locations_at timestamptz;

-- the user may change it (account window / the one-time question at login)
grant update (share_locations) on public.profiles to authenticated;

create or replace function public.touch_share_locations()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if new.share_locations is distinct from old.share_locations then
        new.share_locations_at := case when new.share_locations then now() end;
    end if;
    return new;
end
$$;

create trigger profiles_touch_share_locations
    before update of share_locations on public.profiles
    for each row execute function public.touch_share_locations();

-- sign-up: take the tick from the metadata (the GUI sends share_locations)
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    md      jsonb := coalesce(new.raw_user_meta_data, '{}'::jsonb);
    version text  := nullif(btrim(md ->> 'privacy_version'), '');
    share   boolean := coalesce((md ->> 'share_locations')::boolean, false);
begin
    if version is null then
        raise exception 'privacy consent missing'
            using errcode = '23514',
                  hint = 'Sign-up needs options.data.privacy_version';
    end if;
    insert into public.profiles (id, username, full_name, country, institute,
                                 privacy_version, privacy_accepted_at,
                                 share_locations, share_locations_at)
    values (new.id,
            btrim(md ->> 'username'),
            nullif(btrim(md ->> 'full_name'), ''),
            nullif(btrim(md ->> 'country'), ''),
            nullif(btrim(md ->> 'institute'), ''),
            left(version, 40),
            now(),
            share,
            case when share then now() end);
    return new;
end
$$;

-- ---------------------------------------------------------------------------
-- the anonymous dataset + the quota
-- ---------------------------------------------------------------------------
create table public.run_locations (
    lon   numeric(6, 2) not null check (lon between -180 and 180),
    lat   numeric(5, 2) not null check (lat between -90 and 90),
    month date not null check (extract(day from month) = 1),
    runs  integer not null default 0 check (runs >= 0),
    primary key (lon, lat, month)
);

create table public.location_quota (
    user_id uuid not null references auth.users (id) on delete cascade,
    day     date not null,
    n       integer not null default 0,
    primary key (user_id, day)
);

insert into public.game_config (key, value, description) values
    ('location_daily_cap', '50', 'Run locations one user may report per day (0 = no cap)')
on conflict (key) do nothing;

-- No client access at all: the dataset is read by IIASA in the dashboard / SQL.
revoke all on table public.run_locations, public.location_quota from anon, authenticated;
alter table public.run_locations  enable row level security;
alter table public.location_quota enable row level security;

-- ---------------------------------------------------------------------------
-- record_run_location - one successful run's first gauge
-- ---------------------------------------------------------------------------
-- Returns {status}: recorded | no_consent | invalid_location | daily_limit
create or replace function public.record_run_location(p_lon double precision,
                                                      p_lat double precision)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_user  uuid := auth.uid();
    v_cap   integer := public._game_int('location_daily_cap', 50);
    v_n     integer;
begin
    if v_user is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;
    if not exists (select 1 from public.profiles p
                   where p.id = v_user and p.share_locations) then
        return jsonb_build_object('status', 'no_consent');
    end if;
    if p_lon is null or p_lat is null or p_lon < -180 or p_lon > 180
       or p_lat < -90 or p_lat > 90 or (p_lon = 0 and p_lat = 0) then
        return jsonb_build_object('status', 'invalid_location');
    end if;

    insert into public.location_quota (user_id, day, n)
    values (v_user, current_date, 1)
    on conflict (user_id, day) do update set n = public.location_quota.n + 1
    returning n into v_n;
    delete from public.location_quota q where q.day < current_date - 1;
    if v_cap > 0 and v_n > v_cap then
        return jsonb_build_object('status', 'daily_limit');
    end if;

    insert into public.run_locations (lon, lat, month, runs)
    values (round(p_lon::numeric, 2), round(p_lat::numeric, 2),
            date_trunc('month', now())::date, 1)
    on conflict (lon, lat, month) do update
        set runs = public.run_locations.runs + 1;
    return jsonb_build_object('status', 'recorded');
end
$$;

revoke execute on function public.record_run_location(double precision, double precision)
    from public, anon, authenticated;
grant execute on function public.record_run_location(double precision, double precision)
    to authenticated;
revoke execute on function public.touch_share_locations() from public, anon, authenticated;
revoke execute on function public.handle_new_user() from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- get_my_status: the profile now also says whether locations are shared
-- ---------------------------------------------------------------------------
create or replace function public.get_my_status()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_user  uuid := auth.uid();
    v_total integer;
begin
    if v_user is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;
    v_total := public._total_points(v_user);
    return jsonb_build_object(
        'profile', (select jsonb_build_object(
                        'username', p.username,
                        'full_name', p.full_name,
                        'country', p.country,
                        'institute', p.institute,
                        'show_on_leaderboard', p.show_on_leaderboard,
                        'share_locations', p.share_locations)
                    from public.profiles p where p.id = v_user),
        'total_points', v_total,
        'badges', (select coalesce(jsonb_agg(jsonb_build_object(
                                'code', b.code,
                                'name', b.name,
                                'awarded_at', ub.awarded_at) order by b.sort_order),
                            '[]'::jsonb)
                   from public.user_badges ub
                   join public.badges b on b.code = ub.badge_code
                   where ub.user_id = v_user),
        'next_badge', (select jsonb_build_object(
                                'code', b.code,
                                'name', b.name,
                                'points_required', b.points_required)
                       from public.badges b
                       where b.points_required > v_total
                       order by b.points_required
                       limit 1));
end
$$;

revoke execute on function public.get_my_status() from public, anon, authenticated;
grant execute on function public.get_my_status() to authenticated;

-- ---------------------------------------------------------------------------
-- The dataset for IIASA (dashboard SQL editor), e.g.:
--   select lon, lat, sum(runs) as runs from public.run_locations
--   group by lon, lat order by runs desc;
-- ---------------------------------------------------------------------------
