-- CWatM GUI - Info ▸ World Map ▸ "User location": users who opted in, as points.
--
-- The own location (profiles.location_lat/lon) is personal data. It is shown on the
-- public world map ONLY for users who ticked "Show my location on the world map"
-- (show_location_on_map, default FALSE), WITHOUT names, rounded to 0.01 degree
-- (~1 km) and counted per rounded place - several users at one place are one
-- point with a number.

alter table public.profiles
    add column show_location_on_map boolean not null default false;

grant update (show_location_on_map) on public.profiles to authenticated;

create or replace function public.get_user_locations()
returns table (lat numeric, lon numeric, users bigint)
language sql
stable
security definer
set search_path = ''
as $$
    select round(p.location_lat, 2), round(p.location_lon, 2), count(*)::bigint
    from public.profiles p
    where p.show_location_on_map
      and p.location_lat is not null and p.location_lon is not null
    group by 1, 2
    order by 3 desc
    limit 20000;
$$;

revoke execute on function public.get_user_locations() from public, anon, authenticated;
grant execute on function public.get_user_locations() to anon, authenticated;

-- the GUI's status includes the new choice
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
                        'show_location_on_map', p.show_location_on_map)
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
