-- CWatM GUI gamification - leaderboard badge + no points for repeated settings.
--
-- 1. get_leaderboard() also returns each listed user's highest badge.
-- 2. award_run() awards a point only once per distinct model setup per user: the GUI
--    sends a one-way fingerprint of the settings the run used (meta.settings_hash,
--    SHA-256 hex - see src/gui/utils/run_ledger.py settings_fingerprint); a second
--    run with a setup that already earned a point answers status 'same_settings'.
--    The settings themselves never leave the user's computer. A run without a
--    fingerprint (settings could not be read) is not blocked by this rule.

-- ---------------------------------------------------------------------------
-- 1. leaderboard with the highest badge (return type changes -> drop + create)
-- ---------------------------------------------------------------------------
drop function if exists public.get_leaderboard(integer);

create function public.get_leaderboard(p_limit integer default 50)
returns table (rank bigint, username text, country text, total_points bigint,
               top_badge text)
language sql
stable
security definer
set search_path = ''
as $$
    with totals as (
        select p.id, p.username, p.country,
               coalesce((select sum(e.points) from public.point_events e
                         where e.user_id = p.id), 0)::bigint as total_points
        from public.profiles p
        where p.show_on_leaderboard
    )
    select rank() over (order by t.total_points desc) as rank,
           t.username,
           t.country,
           t.total_points,
           (select b.name
            from public.user_badges ub
            join public.badges b on b.code = ub.badge_code
            where ub.user_id = t.id
            order by b.points_required desc
            limit 1) as top_badge
    from totals t
    -- by position: in a RETURNS TABLE function the output names are also parameters
    order by 4 desc, 2
    limit least(greatest(coalesce(p_limit, 50), 1), 200);
$$;

revoke execute on function public.get_leaderboard(integer) from public, anon, authenticated;
grant execute on function public.get_leaderboard(integer) to anon, authenticated;

-- ---------------------------------------------------------------------------
-- 2. award_run: one point per distinct setup
-- ---------------------------------------------------------------------------
create index if not exists point_events_user_settings_idx
    on public.point_events (user_id, (meta ->> 'settings_hash'))
    where source = 'run';

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
    v_hash      text;
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
    v_hash      := case when p_meta ->> 'settings_hash' ~ '^[0-9a-f]{64}$'
                        then p_meta ->> 'settings_hash' end;

    if v_min > 0 and coalesce(v_timesteps, 0) < v_min then
        return jsonb_build_object('status', 'too_short', 'min_timesteps', v_min);
    end if;

    -- Serialise this user's awards so two parallel calls cannot both slip under
    -- the daily cap (or both count the same new setup).
    perform pg_advisory_xact_lock(hashtext('award_run:' || v_user::text));

    if exists (select 1 from public.point_events e
               where e.user_id = v_user and e.source = 'run' and e.source_ref = p_run_uid) then
        return jsonb_build_object('status', 'duplicate',
                                  'total_points', public._total_points(v_user));
    end if;

    if v_hash is not null and exists (
            select 1 from public.point_events e
            where e.user_id = v_user and e.source = 'run'
              and e.meta ->> 'settings_hash' = v_hash) then
        return jsonb_build_object('status', 'same_settings',
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
        'gui_version',   left(p_meta ->> 'gui_version', 20),
        'kind',          v_kind,
        'timesteps',     v_timesteps,
        'duration_s',    v_duration,
        'settings_hash', v_hash));

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

revoke execute on function public.award_run(text, jsonb) from public, anon, authenticated;
grant execute on function public.award_run(text, jsonb) to authenticated;
