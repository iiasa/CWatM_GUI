-- CWatM GUI - store only what the points rules need (data minimisation).
--
-- A counted RUN keeps only:
--   * the settings fingerprint (SHA-256 of the setup) - now the event's source_ref,
--     so "one point per distinct setup" is the table's own unique key, and
--   * the DAY it was counted (earned_on) - the daily cap counts runs per day.
-- The random run number, GUI version, run kind, number of timesteps and run time are
-- no longer stored. The GUI still SENDS the number of timesteps, because the minimum
-- run length is checked at the moment of counting - it is checked, not stored.
--
-- A finished ACADEMY level keeps only which level it was (source_ref 'academy:<n>'):
-- no date (earned_on is null), no meta.
--
-- The point_events columns meta and created_at are dropped; existing rows are
-- converted (a run's fingerprint moves into source_ref, its date becomes a day).
--
-- The data export (export_my_data) shows the email address masked (p***@g***.com).
--
-- The first gauge's location stays where it was: anonymous counts in run_locations,
-- deliberately never linked to a user or to a run.

-- ---------------------------------------------------------------------------
-- point_events: day only, fingerprint as the key, no meta
-- ---------------------------------------------------------------------------
alter table public.point_events add column earned_on date;

update public.point_events
   set earned_on = case when source = 'training' then null
                        else (created_at at time zone 'UTC')::date end;

-- a run's fingerprint becomes its key (runs from before the fingerprint keep their
-- random number - nothing else is known about them any more)
update public.point_events
   set source_ref = meta ->> 'settings_hash'
 where source = 'run' and meta ->> 'settings_hash' ~ '^[0-9a-f]{64}$';

drop index if exists public.point_events_user_settings_idx;
drop index if exists public.point_events_user_created_idx;
alter table public.point_events drop column meta;
alter table public.point_events drop column created_at;
create index point_events_user_day_idx on public.point_events (user_id, earned_on);

-- ---------------------------------------------------------------------------
-- _award_run_core - same rules, minimal row
--   status: awarded | same_settings | no_settings_hash | too_short | daily_limit |
--           email_not_confirmed
-- p_run_uid is still accepted (older GUIs send it) but no longer stored.
-- ---------------------------------------------------------------------------
create or replace function public._award_run_core(p_run_uid text,
                                                  p_meta jsonb default '{}'::jsonb)
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
    v_hash      text;
    v_today     integer;
    v_rows      integer;
begin
    if v_user is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;

    if not exists (select 1 from auth.users u
                   where u.id = v_user and u.email_confirmed_at is not null) then
        return jsonb_build_object('status', 'email_not_confirmed');
    end if;

    p_meta := coalesce(p_meta, '{}'::jsonb);
    v_timesteps := case when p_meta ->> 'timesteps' ~ '^\d{1,9}$'
                        then (p_meta ->> 'timesteps')::integer end;
    v_hash      := case when p_meta ->> 'settings_hash' ~ '^[0-9a-f]{64}$'
                        then p_meta ->> 'settings_hash' end;

    -- the fingerprint is the run's identity now: without it nothing can be counted
    if v_hash is null then
        return jsonb_build_object('status', 'no_settings_hash',
                                  'total_points', public._total_points(v_user));
    end if;

    if v_min > 0 and coalesce(v_timesteps, 0) < v_min then
        return jsonb_build_object('status', 'too_short', 'min_timesteps', v_min);
    end if;

    perform pg_advisory_xact_lock(hashtext('award_run:' || v_user::text));

    if exists (select 1 from public.point_events e
               where e.user_id = v_user and e.source = 'run' and e.source_ref = v_hash) then
        return jsonb_build_object('status', 'same_settings',
                                  'total_points', public._total_points(v_user));
    end if;

    select count(*) into v_today
    from public.point_events e
    where e.user_id = v_user and e.source = 'run'
      and e.earned_on = (now() at time zone 'UTC')::date;

    if v_cap > 0 and v_today >= v_cap then
        return jsonb_build_object('status', 'daily_limit', 'daily_run_cap', v_cap,
                                  'total_points', public._total_points(v_user));
    end if;

    insert into public.point_events (user_id, source, source_ref, points, earned_on)
    values (v_user, 'run', v_hash, v_points, (now() at time zone 'UTC')::date)
    on conflict (user_id, source, source_ref) do nothing;
    get diagnostics v_rows = row_count;

    if v_rows = 0 then
        return jsonb_build_object('status', 'same_settings',
                                  'total_points', public._total_points(v_user));
    end if;

    return jsonb_build_object(
        'status',         'awarded',
        'points_awarded', v_points,
        'new_badges',     public._award_badges(v_user),
        'total_points',   public._total_points(v_user));
end
$$;

revoke execute on function public._award_run_core(text, jsonb)
    from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- _academy_complete_level_core - which level only: no date, no meta
-- ---------------------------------------------------------------------------
create or replace function public._academy_complete_level_core(p_level integer)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_user   uuid := auth.uid();
    v_points integer := public._game_int('points_per_academy_level', 5);
    v_max    integer := public._game_int('academy_levels', 10);
    v_done   smallint[];
    v_rows   integer := 0;
    v_status text;
begin
    if v_user is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;
    if p_level is null or p_level < 1 or p_level > v_max then
        return jsonb_build_object('status', 'invalid_level');
    end if;

    perform pg_advisory_xact_lock(hashtext('academy:' || v_user::text));

    update public.profiles p
       set academy_completed = (select array_agg(distinct x order by x)
                                from unnest(p.academy_completed
                                            || p_level::smallint) as x)
     where p.id = v_user
    returning p.academy_completed into v_done;

    -- points only for a confirmed email, and once per level
    if exists (select 1 from auth.users u
               where u.id = v_user and u.email_confirmed_at is not null) then
        insert into public.point_events (user_id, source, source_ref, points)
        values (v_user, 'training', 'academy:' || p_level, v_points)
        on conflict (user_id, source, source_ref) do nothing;
        get diagnostics v_rows = row_count;
        v_status := case when v_rows > 0 then 'awarded' else 'already_awarded' end;
    else
        v_status := 'email_not_confirmed';
    end if;

    return jsonb_build_object(
        'status',            v_status,
        'level',             p_level,
        'points_awarded',    case when v_rows > 0 then v_points else 0 end,
        'new_badges',        case when v_rows > 0 then public._award_badges(v_user)
                                  else '[]'::jsonb end,
        'total_points',      public._total_points(v_user),
        'academy_completed', to_jsonb(coalesce(v_done, '{}'::smallint[])));
end
$$;

revoke execute on function public._academy_complete_level_core(integer)
    from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- the email address, masked for the data export: peter@gmail.com -> p***@g***.com
-- ---------------------------------------------------------------------------
create or replace function public._mask_email(p_email text)
returns text
language sql
immutable
set search_path = ''
as $$
    select case
        when p_email is null or position('@' in p_email) = 0 then p_email
        else left(split_part(p_email, '@', 1), 1) || '***@'
             || left(split_part(p_email, '@', 2), 1) || '***'
             || coalesce(substring(split_part(p_email, '@', 2) from '(\.[^.]+)$'), '')
    end;
$$;

revoke execute on function public._mask_email(text) from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- export_my_data - masked email; point events without the internal row id
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
                        'email', public._mask_email(u.email),
                        'created_at', u.created_at,
                        'email_confirmed_at', u.email_confirmed_at,
                        'last_sign_in_at', u.last_sign_in_at)
                    from auth.users u where u.id = v_user),
        'profile', (select to_jsonb(p) from public.profiles p where p.id = v_user),
        'point_events', (select coalesce(jsonb_agg(to_jsonb(e) - 'user_id' - 'id'
                                                   order by e.earned_on nulls first,
                                                            e.source, e.source_ref),
                                         '[]'::jsonb)
                         from public.point_events e where e.user_id = v_user),
        'badges', (select coalesce(jsonb_agg(to_jsonb(ub) - 'user_id' order by ub.awarded_at),
                                   '[]'::jsonb)
                   from public.user_badges ub where ub.user_id = v_user),
        'purchases', (select coalesce(jsonb_agg(to_jsonb(pu) - 'user_id' order by pu.purchased_at),
                                      '[]'::jsonb)
                      from public.purchases pu where pu.user_id = v_user),
        'point_decay', (select coalesce(jsonb_agg(to_jsonb(d) - 'user_id' order by d.decayed_at),
                                        '[]'::jsonb)
                        from public.point_decay d where d.user_id = v_user))
        || public._points_summary(v_user);
end
$$;

revoke execute on function public.export_my_data() from public, anon, authenticated;
grant execute on function public.export_my_data() to authenticated;
