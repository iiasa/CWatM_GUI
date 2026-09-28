-- CWatM GUI gamification - API functions (step S1).
--
-- Called by the GUI (supabase rpc):
--   username_available(p_username)        anon + authenticated
--   award_run(p_run_uid, p_meta)          authenticated
--   get_my_status()                       authenticated
--   export_my_data()                      authenticated
--   get_leaderboard(p_limit)              anon + authenticated (opt-in users only)
-- Called by the login-with-username Edge Function (service role only):
--   _email_for_username, _login_throttled, _login_record
--
-- Every function is security definer with an empty search_path and fully qualified
-- names. Supabase grants EXECUTE on new functions to anon/authenticated by default,
-- so each one's grants are reset explicitly at the bottom.

-- ---------------------------------------------------------------------------
-- internal helpers
-- ---------------------------------------------------------------------------
create or replace function public._game_int(p_key text, p_default integer)
returns integer
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(
        (select (c.value #>> '{}')::integer from public.game_config c where c.key = p_key),
        p_default);
$$;

create or replace function public._total_points(p_user uuid)
returns integer
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(sum(e.points), 0)::integer
    from public.point_events e
    where e.user_id = p_user;
$$;

-- Gives the user every badge their total now reaches; returns the NEW ones.
create or replace function public._award_badges(p_user uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_total  integer := public._total_points(p_user);
    v_new    jsonb;
begin
    with ins as (
        insert into public.user_badges (user_id, badge_code)
        select p_user, b.code
        from public.badges b
        where b.points_required <= v_total
        on conflict do nothing
        returning badge_code
    )
    select coalesce(jsonb_agg(jsonb_build_object(
               'code', b.code,
               'name', b.name,
               'points_required', b.points_required) order by b.sort_order),
           '[]'::jsonb)
    into v_new
    from ins
    join public.badges b on b.code = ins.badge_code;
    return v_new;
end
$$;

-- ---------------------------------------------------------------------------
-- username_available
-- ---------------------------------------------------------------------------
create or replace function public.username_available(p_username text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(p_username ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{2,29}$', false)
       and not exists (select 1 from public.profiles p
                       where lower(p.username) = lower(p_username));
$$;

-- ---------------------------------------------------------------------------
-- award_run - one point (game_config.points_per_run) for a full CWatM run
-- ---------------------------------------------------------------------------
-- p_run_uid : the Journal-of-Runs uid of the run (uuid4 hex, 32 chars) - makes the
--             award idempotent: the same run can never count twice.
-- p_meta    : {gui_version, kind (run|hidden|batch), timesteps, duration_s}; anything
--             else is dropped. The client decides nothing about the points.
-- Returns {status, ...}; status is one of
--   awarded | duplicate | too_short | daily_limit | email_not_confirmed | invalid_run_uid
create or replace function public.award_run(p_run_uid text, p_meta jsonb default '{}'::jsonb)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_user      uuid := auth.uid();
    v_points    integer := public._game_int('points_per_run', 1);
    v_min       integer := public._game_int('min_timesteps', 30);
    v_cap       integer := public._game_int('daily_run_cap', 20);
    v_timesteps integer;
    v_duration  integer;
    v_kind      text;
    v_today     integer;
    v_rows      integer;
    v_meta      jsonb;
begin
    if v_user is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;

    if not exists (select 1 from auth.users u
                   where u.id = v_user and u.email_confirmed_at is not null) then
        return jsonb_build_object('status', 'email_not_confirmed');
    end if;

    if p_run_uid is null or p_run_uid !~ '^[0-9a-f]{32}$' then
        return jsonb_build_object('status', 'invalid_run_uid');
    end if;

    p_meta := coalesce(p_meta, '{}'::jsonb);
    v_timesteps := case when p_meta ->> 'timesteps' ~ '^\d{1,9}$'
                        then (p_meta ->> 'timesteps')::integer end;
    v_duration  := case when p_meta ->> 'duration_s' ~ '^\d{1,9}(\.\d+)?$'
                        then round((p_meta ->> 'duration_s')::numeric)::integer end;
    v_kind      := case when p_meta ->> 'kind' in ('run', 'hidden', 'batch')
                        then p_meta ->> 'kind' end;

    if v_min > 0 and coalesce(v_timesteps, 0) < v_min then
        return jsonb_build_object('status', 'too_short', 'min_timesteps', v_min);
    end if;

    -- Serialise this user's awards so two parallel calls cannot both slip under
    -- the daily cap.
    perform pg_advisory_xact_lock(hashtext('award_run:' || v_user::text));

    if exists (select 1 from public.point_events e
               where e.user_id = v_user and e.source = 'run' and e.source_ref = p_run_uid) then
        return jsonb_build_object('status', 'duplicate',
                                  'total_points', public._total_points(v_user));
    end if;

    select count(*) into v_today
    from public.point_events e
    where e.user_id = v_user and e.source = 'run'
      and e.created_at > now() - interval '24 hours';

    if v_cap > 0 and v_today >= v_cap then
        return jsonb_build_object('status', 'daily_limit', 'daily_run_cap', v_cap,
                                  'total_points', public._total_points(v_user));
    end if;

    v_meta := jsonb_strip_nulls(jsonb_build_object(
        'gui_version', left(p_meta ->> 'gui_version', 20),
        'kind',        v_kind,
        'timesteps',   v_timesteps,
        'duration_s',  v_duration));

    insert into public.point_events (user_id, source, source_ref, points, meta)
    values (v_user, 'run', p_run_uid, v_points, v_meta)
    on conflict (user_id, source, source_ref) do nothing;
    get diagnostics v_rows = row_count;

    if v_rows = 0 then
        return jsonb_build_object('status', 'duplicate',
                                  'total_points', public._total_points(v_user));
    end if;

    return jsonb_build_object(
        'status',         'awarded',
        'points_awarded', v_points,
        'new_badges',     public._award_badges(v_user),
        'total_points',   public._total_points(v_user));
end
$$;

-- ---------------------------------------------------------------------------
-- get_my_status - what the GUI's account indicator shows
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
                        'show_on_leaderboard', p.show_on_leaderboard)
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

-- ---------------------------------------------------------------------------
-- export_my_data - GDPR data export (everything stored about the caller)
-- ---------------------------------------------------------------------------
create or replace function public.export_my_data()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_user uuid := auth.uid();
begin
    if v_user is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;
    return jsonb_build_object(
        'exported_at', now(),
        'account', (select jsonb_build_object(
                        'email', u.email,
                        'created_at', u.created_at,
                        'email_confirmed_at', u.email_confirmed_at,
                        'last_sign_in_at', u.last_sign_in_at)
                    from auth.users u where u.id = v_user),
        'profile', (select to_jsonb(p) from public.profiles p where p.id = v_user),
        'point_events', (select coalesce(jsonb_agg(to_jsonb(e) - 'user_id' order by e.created_at),
                                         '[]'::jsonb)
                         from public.point_events e where e.user_id = v_user),
        'badges', (select coalesce(jsonb_agg(to_jsonb(ub) - 'user_id' order by ub.awarded_at),
                                   '[]'::jsonb)
                   from public.user_badges ub where ub.user_id = v_user));
end
$$;

-- ---------------------------------------------------------------------------
-- get_leaderboard - only users who ticked show_on_leaderboard; username + country
-- ---------------------------------------------------------------------------
create or replace function public.get_leaderboard(p_limit integer default 50)
returns table (rank bigint, username text, country text, total_points bigint)
language sql
stable
security definer
set search_path = ''
as $$
    select rank() over (order by coalesce(sum(e.points), 0) desc) as rank,
           p.username,
           p.country,
           coalesce(sum(e.points), 0)::bigint as total_points
    from public.profiles p
    left join public.point_events e on e.user_id = p.id
    where p.show_on_leaderboard
    group by p.id, p.username, p.country
    -- by position: in a RETURNS TABLE function the output names are also parameters
    order by 4 desc, 2
    limit least(greatest(coalesce(p_limit, 50), 1), 200);
$$;

-- ---------------------------------------------------------------------------
-- login-with-username support (service role only)
-- ---------------------------------------------------------------------------
create or replace function public._email_for_username(p_username text)
returns text
language sql
stable
security definer
set search_path = ''
as $$
    select u.email
    from public.profiles p
    join auth.users u on u.id = p.id
    where lower(p.username) = lower(p_username);
$$;

-- true = too many failed attempts for this username inside the window.
create or replace function public._login_throttled(p_username text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select count(*) >= public._game_int('login_max_failures', 10)
    from public.login_attempts a
    where lower(a.username) = lower(p_username)
      and a.attempted_at > now()
          - make_interval(mins => public._game_int('login_window_minutes', 15));
$$;

-- Failure: record it. Success: forget this username's failures. Either way old
-- rows (older than a day) are pruned so the table stays small.
create or replace function public._login_record(p_username text, p_success boolean)
returns void
language plpgsql
volatile
security definer
set search_path = ''
as $$
begin
    if p_success then
        delete from public.login_attempts a where lower(a.username) = lower(p_username);
    else
        insert into public.login_attempts (username) values (left(p_username, 60));
    end if;
    delete from public.login_attempts a where a.attempted_at < now() - interval '1 day';
end
$$;

-- ---------------------------------------------------------------------------
-- grants
-- ---------------------------------------------------------------------------
revoke execute on function
    public.touch_updated_at(),
    public.handle_new_user(),
    public._game_int(text, integer),
    public._total_points(uuid),
    public._award_badges(uuid),
    public.username_available(text),
    public.award_run(text, jsonb),
    public.get_my_status(),
    public.export_my_data(),
    public.get_leaderboard(integer),
    public._email_for_username(text),
    public._login_throttled(text),
    public._login_record(text, boolean)
    from public, anon, authenticated;

grant execute on function public.username_available(text)    to anon, authenticated;
grant execute on function public.get_leaderboard(integer)     to anon, authenticated;
grant execute on function public.award_run(text, jsonb)       to authenticated;
grant execute on function public.get_my_status()              to authenticated;
grant execute on function public.export_my_data()             to authenticated;

grant execute on function public._email_for_username(text)       to service_role;
grant execute on function public._login_throttled(text)          to service_role;
grant execute on function public._login_record(text, boolean)    to service_role;
