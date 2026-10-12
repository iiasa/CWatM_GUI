-- CWatM GUI - feature badges: bronze / silver / gold for successful runs with a model
-- feature switched on. Generalises the MoleFlow badges (..._moleflow_badges.sql):
--
--   modflow     MoleFlow      modflow_coupling = True   (bronze comes with the mole)
--   pysnowclim  pySnowClim    usepySnowClim = True
--   glacier     Glacier OGGM  includeGlaciers = True
--
-- bronze at the first such run, silver at 20, gold at 50 (_moleflow_tier). Like the
-- MoleFlow badge each tier REPLACES the one before; the three features are separate.
-- No points come with them.
--
--   profiles.pysnowclim_runs, profiles.glacier_runs   (profiles.modflow_runs exists)
--   written ONLY by record_feature_run / record_modflow_run (no column grants).

alter table public.profiles
    add column pysnowclim_runs integer not null default 0 check (pysnowclim_runs >= 0),
    add column glacier_runs    integer not null default 0 check (glacier_runs >= 0);

-- ---------------------------------------------------------------------------
-- get_feature_badges - {modflow: {runs, tier}, pysnowclim: {...}, glacier: {...}}
-- ---------------------------------------------------------------------------
create or replace function public.get_feature_badges()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_user uuid := auth.uid();
    v_row  record;
begin
    if v_user is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;
    select coalesce(p.modflow_runs, 0) as m, coalesce(p.pysnowclim_runs, 0) as s,
           coalesce(p.glacier_runs, 0) as g
      into v_row from public.profiles p where p.id = v_user;
    return jsonb_build_object(
        'modflow',    jsonb_build_object('runs', coalesce(v_row.m, 0),
                                         'tier', public._moleflow_tier(coalesce(v_row.m, 0))),
        'pysnowclim', jsonb_build_object('runs', coalesce(v_row.s, 0),
                                         'tier', public._moleflow_tier(coalesce(v_row.s, 0))),
        'glacier',    jsonb_build_object('runs', coalesce(v_row.g, 0),
                                         'tier', public._moleflow_tier(coalesce(v_row.g, 0))));
end
$$;

revoke execute on function public.get_feature_badges() from public, anon, authenticated;
grant execute on function public.get_feature_badges() to authenticated;

-- ---------------------------------------------------------------------------
-- record_feature_run - count successful runs with a feature on (p_runs: 1, or more
-- for runs kept while logged out; at most 100 at once)
--   {status, feature, runs, tier, previous_tier, new_tier}
-- ---------------------------------------------------------------------------
create or replace function public.record_feature_run(p_feature text, p_runs integer default 1)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_user uuid := auth.uid();
    v_old  integer;
    v_new  integer;
begin
    if v_user is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;
    if p_feature is null or p_feature not in ('modflow', 'pysnowclim', 'glacier') then
        return jsonb_build_object('status', 'unknown_feature', 'feature', p_feature);
    end if;
    if p_runs is null or p_runs < 1 or p_runs > 100 then
        return jsonb_build_object('status', 'invalid_runs', 'feature', p_feature);
    end if;

    select case p_feature when 'modflow'    then p.modflow_runs
                          when 'pysnowclim' then p.pysnowclim_runs
                          else p.glacier_runs end
      into v_old
      from public.profiles p where p.id = v_user for update;
    v_old := coalesce(v_old, 0);
    v_new := v_old + p_runs;

    update public.profiles p
       set modflow_runs    = case when p_feature = 'modflow'    then v_new else p.modflow_runs end,
           pysnowclim_runs = case when p_feature = 'pysnowclim' then v_new else p.pysnowclim_runs end,
           glacier_runs    = case when p_feature = 'glacier'    then v_new else p.glacier_runs end
     where p.id = v_user;

    return jsonb_build_object(
        'status',        'recorded',
        'feature',       p_feature,
        'runs',          v_new,
        'tier',          public._moleflow_tier(v_new),
        'previous_tier', public._moleflow_tier(v_old),
        'new_tier',      public._moleflow_tier(v_new)
                             is distinct from public._moleflow_tier(v_old));
end
$$;

revoke execute on function public.record_feature_run(text, integer) from public, anon, authenticated;
grant execute on function public.record_feature_run(text, integer) to authenticated;
