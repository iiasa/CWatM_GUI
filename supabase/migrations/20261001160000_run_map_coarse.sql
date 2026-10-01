-- CWatM GUI - the PUBLIC run map shows places at 0.1 degree (~10 km), not 0.001 (~100 m)
-- (security.md finding 9).
--
-- run_locations keeps its 0.001-degree counts (closed to clients, no user column).
-- Only what get_run_locations() hands to everyone - anon included - is coarsened:
-- one gauge at ~100 m, combined with knowing who models that river, said more about
-- a person than the 0.5-degree own location does. The GUI's map draws whatever this
-- returns, so no GUI change is needed for the numbers.
--
-- game_config 'run_map_min_runs' (default 1): a place is listed only from this many
-- runs on. Raise it (e.g. to 3) to hide places with a single run:
--   update public.game_config set value = '3' where key = 'run_map_min_runs';

insert into public.game_config (key, value, description) values
    ('run_map_min_runs', '1',
     'Public world map: a 0.1-degree place is shown only from this many runs on')
on conflict (key) do nothing;

create or replace function public.get_run_locations()
returns table (lon numeric, lat numeric, runs bigint)
language sql
stable
security definer
set search_path = ''
as $$
    select round(r.lon, 1), round(r.lat, 1), sum(r.runs)::bigint
    from public.run_locations r
    group by 1, 2
    having sum(r.runs) >= greatest(1, public._game_int('run_map_min_runs', 1))
    order by 3 desc
    limit 20000;
$$;

revoke execute on function public.get_run_locations() from public, anon, authenticated;
grant execute on function public.get_run_locations() to anon, authenticated;
