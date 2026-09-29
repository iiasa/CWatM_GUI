-- CWatM GUI - run locations rounded to 0.001 degree (~100 m) instead of 0.01 (~1 km).
-- Existing counts keep their 2-decimal coordinates (a numeric(7,3) holds them
-- unchanged); new reports are rounded to 3 decimals.

alter table public.run_locations
    alter column lon type numeric(7, 3),
    alter column lat type numeric(6, 3);

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
    values (round(p_lon::numeric, 3), round(p_lat::numeric, 3),
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
