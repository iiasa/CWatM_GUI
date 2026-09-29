-- CWatM GUI - Info ▸ World Map: read the anonymous run-location counts.
--
-- run_locations itself stays closed to clients. This function returns only the
-- totals per location (summed over all months) - the same anonymous numbers, no
-- user, no months. Public (anon + authenticated): the GUI shows the map to every
-- user, logged in or not; the privacy notice says the counts are shown this way.

create or replace function public.get_run_locations()
returns table (lon numeric, lat numeric, runs bigint)
language sql
stable
security definer
set search_path = ''
as $$
    select r.lon, r.lat, sum(r.runs)::bigint
    from public.run_locations r
    group by r.lon, r.lat
    having sum(r.runs) > 0
    order by 3 desc
    limit 20000;
$$;

revoke execute on function public.get_run_locations() from public, anon, authenticated;
grant execute on function public.get_run_locations() to anon, authenticated;
