-- CWatM GUI - feature badge runs follow the same rules as the points for runs.
--
-- A successful run with coupled MODFLOW / pySnowClim / glaciers now counts for its
-- feature badge (..._feature_badges.sql) only like a run counts for a point
-- (_award_run_core):
--   * it carries the settings fingerprint (SHA-256, Title/PathOut/OUT_* left out)
--   * it has at least game_config 'min_timesteps' timesteps
--   * the same settings count once per feature - a changed setup counts again
--   * at most game_config 'daily_run_cap' runs per feature and day
--
--   feature_run_settings   one row per (user, feature, settings fingerprint) and the
--                          day it was counted - nothing else. Read and written only
--                          by record_feature_run (RLS on, no policies); deleted
--                          with the account (on delete cascade).
-- profiles.<feature>_runs stays the count (runs counted before this rule keep
-- counting), raised by one for every fingerprint new for that feature.

create table public.feature_run_settings (
    user_id       uuid not null references auth.users (id) on delete cascade,
    feature       text not null check (feature in ('modflow', 'pysnowclim', 'glacier')),
    settings_hash text not null check (settings_hash ~ '^[0-9a-f]{64}$'),
    counted_on    date not null default ((now() at time zone 'UTC')::date),
    primary key (user_id, feature, settings_hash)
);

create index feature_run_settings_day_idx
    on public.feature_run_settings (user_id, feature, counted_on);

alter table public.feature_run_settings enable row level security;
-- no policies: only the definer functions below read or write it

-- the old signature counted any run - replaced
drop function if exists public.record_feature_run(text, integer);

-- ---------------------------------------------------------------------------
-- record_feature_run - one run, with the same meta as award_run:
--   p_meta {settings_hash, timesteps}
--   {status: recorded | same_settings | no_settings_hash | too_short | daily_limit |
--            unknown_feature, feature, runs, tier, previous_tier, new_tier}
-- ---------------------------------------------------------------------------
create or replace function public.record_feature_run(p_feature text, p_meta jsonb)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_user  uuid := auth.uid();
    v_min   integer := public._game_int('min_timesteps', 30);
    v_cap   integer := public._game_int('daily_run_cap', 20);
    v_hash  text;
    v_steps integer;
    v_old   integer;
    v_new   integer;
    v_rows  integer := 0;
    v_today date := (now() at time zone 'UTC')::date;
begin
    if v_user is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;
    if p_feature is null or p_feature not in ('modflow', 'pysnowclim', 'glacier') then
        return jsonb_build_object('status', 'unknown_feature', 'feature', p_feature);
    end if;

    perform pg_advisory_xact_lock(hashtext('feature:' || v_user::text));
    select case p_feature when 'modflow'    then p.modflow_runs
                          when 'pysnowclim' then p.pysnowclim_runs
                          else p.glacier_runs end
      into v_old from public.profiles p where p.id = v_user;
    v_old := coalesce(v_old, 0);

    v_hash := case when coalesce(p_meta, '{}'::jsonb) ->> 'settings_hash' ~ '^[0-9a-f]{64}$'
                   then p_meta ->> 'settings_hash' end;
    v_steps := case when coalesce(p_meta, '{}'::jsonb) ->> 'timesteps' ~ '^[0-9]{1,9}$'
                    then (p_meta ->> 'timesteps')::integer else 0 end;

    if v_hash is null then
        return jsonb_build_object('status', 'no_settings_hash', 'feature', p_feature,
                                  'runs', v_old, 'tier', public._moleflow_tier(v_old));
    end if;
    if v_steps < v_min then
        return jsonb_build_object('status', 'too_short', 'feature', p_feature,
                                  'min_timesteps', v_min, 'runs', v_old,
                                  'tier', public._moleflow_tier(v_old));
    end if;
    if exists (select 1 from public.feature_run_settings f
               where f.user_id = v_user and f.feature = p_feature
                 and f.settings_hash = v_hash) then
        return jsonb_build_object('status', 'same_settings', 'feature', p_feature,
                                  'runs', v_old, 'tier', public._moleflow_tier(v_old));
    end if;
    if (select count(*) from public.feature_run_settings f
        where f.user_id = v_user and f.feature = p_feature
          and f.counted_on = v_today) >= v_cap then
        return jsonb_build_object('status', 'daily_limit', 'feature', p_feature,
                                  'daily_run_cap', v_cap, 'runs', v_old,
                                  'tier', public._moleflow_tier(v_old));
    end if;

    insert into public.feature_run_settings (user_id, feature, settings_hash, counted_on)
    values (v_user, p_feature, v_hash, v_today)
    on conflict do nothing;
    get diagnostics v_rows = row_count;
    v_new := v_old + v_rows;

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

revoke execute on function public.record_feature_run(text, jsonb) from public, anon, authenticated;
grant execute on function public.record_feature_run(text, jsonb) to authenticated;

-- the counting-without-rules MoleFlow function of ..._moleflow_badges.sql is
-- closed too (no GUI release ever called it)
revoke execute on function public.record_modflow_run(integer) from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- export_my_data - as in ..._minimal_point_data.sql plus the feature runs
-- ---------------------------------------------------------------------------
create or replace function public.export_my_data()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_user uuid := auth.uid();
begin
    if v_user is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;
    return jsonb_build_object(
        'exported_at', now(),
        'account', (select jsonb_build_object(
                        'email', public._mask_email(u.email),
                        'created_at', u.created_at,
                        'email_confirmed_at', u.email_confirmed_at,
                        'last_sign_in_at', u.last_sign_in_at)
                    from auth.users u where u.id = v_user),
        'profile', (select to_jsonb(p) from public.profiles p where p.id = v_user),
        'point_events', (select coalesce(jsonb_agg(to_jsonb(e) - 'user_id' - 'id'
                                                   order by e.earned_on nulls first,
                                                            e.source, e.source_ref),
                                         '[]'::jsonb)
                         from public.point_events e where e.user_id = v_user),
        'badges', (select coalesce(jsonb_agg(to_jsonb(ub) - 'user_id' order by ub.awarded_at),
                                   '[]'::jsonb)
                   from public.user_badges ub where ub.user_id = v_user),
        'purchases', (select coalesce(jsonb_agg(to_jsonb(pu) - 'user_id' order by pu.purchased_at),
                                      '[]'::jsonb)
                      from public.purchases pu where pu.user_id = v_user),
        'point_decay', (select coalesce(jsonb_agg(to_jsonb(d) - 'user_id' order by d.decayed_at),
                                        '[]'::jsonb)
                        from public.point_decay d where d.user_id = v_user),
        'feature_runs', (select coalesce(jsonb_agg(to_jsonb(f) - 'user_id'
                                                   order by f.feature, f.counted_on),
                                         '[]'::jsonb)
                         from public.feature_run_settings f where f.user_id = v_user))
        || public._points_summary(v_user);
end
$$;

revoke execute on function public.export_my_data() from public, anon, authenticated;
grant execute on function public.export_my_data() to authenticated;
