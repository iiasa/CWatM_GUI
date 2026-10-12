-- CWatM GUI - the MoleFlow badges: bronze, silver and gold for successful runs with
-- coupled MODFLOW.
--
--   bronze  the first such run - it comes together with the mole
--           (claim_reward('modflow_first_run'))
--   silver  20 runs
--   gold    50 runs
--
-- Unlike the river badges (which are collected), a MoleFlow badge REPLACES the one
-- before: a user holds at most one of them, the highest reached.
--
--   profiles.modflow_runs   successful coupled-MODFLOW runs counted for the account.
--                           Written ONLY by record_modflow_run (no column grant).
-- The tier is computed from the count, never stored. No points come with it.

alter table public.profiles
    add column modflow_runs integer not null default 0 check (modflow_runs >= 0);

-- whoever already got the mole has had their first MODFLOW run: that is bronze
update public.profiles p
   set modflow_runs = 1
 where p.modflow_runs = 0
   and exists (select 1 from public.purchases pu
               join public.shop_items si on si.code = pu.item_code
               where pu.user_id = p.id and si.reward = 'modflow_first_run');

-- ---------------------------------------------------------------------------
-- _moleflow_tier - bronze | silver | gold | null for a run count
-- ---------------------------------------------------------------------------
create or replace function public._moleflow_tier(p_runs integer)
returns text
language sql
immutable
set search_path = ''
as $$
    select case when p_runs >= 50 then 'gold'
                when p_runs >= 20 then 'silver'
                when p_runs >= 1  then 'bronze'
           end;
$$;

revoke execute on function public._moleflow_tier(integer) from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- get_moleflow - {modflow_runs, tier}
-- ---------------------------------------------------------------------------
create or replace function public.get_moleflow()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_user uuid := auth.uid();
    v_runs integer;
begin
    if v_user is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;
    select p.modflow_runs into v_runs from public.profiles p where p.id = v_user;
    v_runs := coalesce(v_runs, 0);
    return jsonb_build_object('modflow_runs', v_runs,
                              'tier', public._moleflow_tier(v_runs));
end
$$;

revoke execute on function public.get_moleflow() from public, anon, authenticated;
grant execute on function public.get_moleflow() to authenticated;

-- ---------------------------------------------------------------------------
-- record_modflow_run - count successful coupled-MODFLOW runs (p_runs: 1, or more
-- for runs kept while logged out / offline; at most 100 at once)
--   {modflow_runs, tier, previous_tier, new_tier: true when the tier went up}
-- ---------------------------------------------------------------------------
create or replace function public.record_modflow_run(p_runs integer default 1)
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
    if p_runs is null or p_runs < 1 or p_runs > 100 then
        return public.get_moleflow() || jsonb_build_object('status', 'invalid_runs');
    end if;
    select p.modflow_runs into v_old from public.profiles p
     where p.id = v_user for update;
    v_old := coalesce(v_old, 0);
    update public.profiles p set modflow_runs = v_old + p_runs
     where p.id = v_user
    returning p.modflow_runs into v_new;
    v_new := coalesce(v_new, v_old);
    return jsonb_build_object(
        'status',        'recorded',
        'modflow_runs',  v_new,
        'tier',          public._moleflow_tier(v_new),
        'previous_tier', public._moleflow_tier(v_old),
        'new_tier',      public._moleflow_tier(v_new)
                             is distinct from public._moleflow_tier(v_old));
end
$$;

revoke execute on function public.record_modflow_run(integer) from public, anon, authenticated;
grant execute on function public.record_modflow_run(integer) to authenticated;
