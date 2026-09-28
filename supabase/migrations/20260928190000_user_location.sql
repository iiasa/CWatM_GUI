-- CWatM GUI - the user's own location as optional profile data.
--
-- location_lat / location_lon: where the user is (optional, like name / country /
-- institute). PERSONAL data - linked to the account, visible only to the user (own
-- profile, export), deleted with the account. Unrelated to the anonymous
-- run_locations (which never hold a user).

alter table public.profiles
    add column location_lat numeric(6, 3) check (location_lat between -90 and 90),
    add column location_lon numeric(7, 3) check (location_lon between -180 and 180),
    add constraint profiles_location_both_or_none
        check ((location_lat is null) = (location_lon is null));

grant update (location_lat, location_lon) on public.profiles to authenticated;

-- sign-up: optional location from the metadata
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
    v_lat   numeric := case when md ->> 'location_lat' ~ '^-?\d{1,3}(\.\d+)?$'
                            then round((md ->> 'location_lat')::numeric, 3) end;
    v_lon   numeric := case when md ->> 'location_lon' ~ '^-?\d{1,3}(\.\d+)?$'
                            then round((md ->> 'location_lon')::numeric, 3) end;
begin
    if version is null then
        raise exception 'privacy consent missing'
            using errcode = '23514',
                  hint = 'Sign-up needs options.data.privacy_version';
    end if;
    if v_lat is null or v_lon is null
       or v_lat not between -90 and 90 or v_lon not between -180 and 180 then
        v_lat := null;
        v_lon := null;
    end if;
    insert into public.profiles (id, username, full_name, country, institute,
                                 privacy_version, privacy_accepted_at,
                                 share_locations, share_locations_at,
                                 location_lat, location_lon)
    values (new.id,
            btrim(md ->> 'username'),
            nullif(btrim(md ->> 'full_name'), ''),
            nullif(btrim(md ->> 'country'), ''),
            nullif(btrim(md ->> 'institute'), ''),
            left(version, 40),
            now(),
            share,
            case when share then now() end,
            v_lat,
            v_lon);
    return new;
end
$$;

revoke execute on function public.handle_new_user() from public, anon, authenticated;

-- the status shown in the GUI now includes the location
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
                        'location_lon', p.location_lon)
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
