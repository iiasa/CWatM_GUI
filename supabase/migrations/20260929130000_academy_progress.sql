-- CWatM GUI - CWatM Academy progress in the user's profile + points per level.
--
-- Preferences ▸ CWatM Academy ▸ "Link CWatM Academy to your login" (default on):
-- while logged in, the Academy's progress is kept in the profile, so the user
-- continues from the same level on any computer, and every finished level earns
-- points (game_config 'points_per_academy_level', default 5).
--
--   profiles.academy_completed   the finished level ids (1-based). Written ONLY by
--                                the functions below (no column grant), so the
--                                client cannot fake it with a profile update.
--   point_events source 'training', source_ref 'academy:<level>'
--                                a level pays once per user - ever: Start Over
--                                clears the progress, not the points.

alter table public.profiles
    add column academy_completed smallint[] not null default '{}';

insert into public.game_config (key, value, description) values
    ('points_per_academy_level', '5', 'Points for each finished CWatM Academy level'),
    ('academy_levels',           '10', 'Number of CWatM Academy levels (valid ids 1..n)')
on conflict (key) do nothing;

-- ---------------------------------------------------------------------------
-- academy_complete_level - record a finished level; award its points once
-- ---------------------------------------------------------------------------
create or replace function public.academy_complete_level(p_level integer)
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
        insert into public.point_events (user_id, source, source_ref, points, meta)
        values (v_user, 'training', 'academy:' || p_level, v_points,
                jsonb_build_object('academy_level', p_level))
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

revoke execute on function public.academy_complete_level(integer) from public, anon, authenticated;
grant execute on function public.academy_complete_level(integer) to authenticated;

-- ---------------------------------------------------------------------------
-- academy_reset - Start Over: clear the progress (the points stay)
-- ---------------------------------------------------------------------------
create or replace function public.academy_reset()
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_user uuid := auth.uid();
begin
    if v_user is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;
    update public.profiles set academy_completed = '{}' where id = v_user;
    return jsonb_build_object('status', 'reset', 'academy_completed', '[]'::jsonb);
end
$$;

revoke execute on function public.academy_reset() from public, anon, authenticated;
grant execute on function public.academy_reset() to authenticated;

-- ---------------------------------------------------------------------------
-- get_my_status - the profile now carries academy_completed
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
                        'share_locations', p.share_locations,
                        'location_lat', p.location_lat,
                        'location_lon', p.location_lon,
                        'show_location_on_map', p.show_location_on_map,
                        'academy_completed', to_jsonb(p.academy_completed))
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
