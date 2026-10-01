-- CWatM GUI - the own location (profiles.location_lat/lon) is kept only to the
-- nearest 0.5 degree (~50 km) instead of 0.001 degree, and shown on the world map
-- (get_user_locations) at that same 0.5 degree instead of 0.01 degree (~1 km).
--
-- The rounding is enforced HERE, by a trigger on profiles, so it holds whatever a
-- client sends (the sign-up trigger handle_new_user, a direct profile update). The
-- GUI rounds the same way before sending (account_validation.round_location).
-- Postgres' numeric round() rounds halves away from zero - the GUI does the same.

create or replace function public._profiles_round_location()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if new.location_lat is not null then
        new.location_lat := round(new.location_lat * 2) / 2;
    end if;
    if new.location_lon is not null then
        new.location_lon := round(new.location_lon * 2) / 2;
    end if;
    return new;
end
$$;

drop trigger if exists profiles_round_location on public.profiles;
create trigger profiles_round_location
    before insert or update of location_lat, location_lon on public.profiles
    for each row execute function public._profiles_round_location();

-- the locations already stored: coarsened now (the trigger fires on this update)
update public.profiles
   set location_lat = location_lat, location_lon = location_lon
 where location_lat is not null or location_lon is not null;

create or replace function public.get_user_locations()
returns table (lat numeric, lon numeric, users bigint)
language sql
stable
security definer
set search_path = ''
as $$
    select round(p.location_lat * 2) / 2, round(p.location_lon * 2) / 2,
           count(*)::bigint
    from public.profiles p
    where p.show_location_on_map
      and p.location_lat is not null and p.location_lon is not null
    group by 1, 2
    order by 3 desc
    limit 20000;
$$;

revoke execute on function public.get_user_locations() from public, anon, authenticated;
grant execute on function public.get_user_locations() to anon, authenticated;
