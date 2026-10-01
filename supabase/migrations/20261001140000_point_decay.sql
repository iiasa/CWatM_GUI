-- CWatM GUI - point decay (see shop.md, "Point decay").
--
-- The ACTUAL points (the balance spent in the Shop) decay while CWatM GUI is not
-- used: after the first week without use -3 %, every further week -5 % of what is
-- left (compounding), rounded to whole points, never below 5 (a balance of 5 or less
-- does not decay). Earned points and badges NEVER decay.
--
-- "Use" = a login (touch_activity(), called by the GUI after every login and
-- automatic re-login). The clock of existing accounts starts now, so nobody loses
-- points at once.
--
--   profiles.last_active_at        last use (date + time of the last login)
--   profiles.decay_weeks_applied   whole weeks since last_active_at already decayed
--   point_decay                    one row per decay that was recorded
--
--   balance          = earned - spent - recorded decay              (_balance)
--   current balance  = balance - decay that is due but not recorded (_current_balance)
--
-- The current balance is what the status, the leaderboard and the Shop show: someone
-- away for a month is lower on the leaderboard already, not only after coming back.
-- touch_activity() and shop_buy() first RECORD the due decay (_settle_decay), under
-- the same per-user lock as the Shop.

alter table public.profiles
    add column last_active_at      timestamptz not null default now(),
    add column decay_weeks_applied integer     not null default 0
        check (decay_weeks_applied >= 0);

insert into public.game_config (key, value, description) values
    ('decay_first_week_pct', '3', 'Point decay after the first week without use (%)'),
    ('decay_weekly_pct',     '5', 'Point decay for every further week without use (%)'),
    ('decay_min_points',     '5', 'Points never decay below this')
on conflict (key) do nothing;

create table public.point_decay (
    id           bigint generated always as identity primary key,
    user_id      uuid not null references auth.users (id) on delete cascade,
    points       integer not null check (points > 0),
    weeks        integer not null check (weeks > 0),     -- weeks without use, in total
    from_balance integer not null,
    decayed_at   timestamptz not null default now()
);

create index point_decay_user_idx on public.point_decay (user_id, decayed_at);

revoke all on table public.point_decay from anon, authenticated;
alter table public.point_decay enable row level security;
grant select on public.point_decay to authenticated;
create policy "point_decay: read own" on public.point_decay
    for select to authenticated
    using ((select auth.uid()) = user_id);

-- ---------------------------------------------------------------------------
-- helpers
-- ---------------------------------------------------------------------------
create or replace function public._decayed_points(p_user uuid)
returns integer
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(sum(d.points), 0)::integer
    from public.point_decay d
    where d.user_id = p_user;
$$;

-- balance = earned - spent - recorded decay (replaces the Shop's version)
create or replace function public._balance(p_user uuid)
returns integer
language sql
stable
security definer
set search_path = ''
as $$
    select public._total_points(p_user) - public._spent_points(p_user)
           - public._decayed_points(p_user);
$$;

-- The decay due now and not yet recorded: points to take, new weeks, total weeks.
create or replace function public._decay_due(p_user uuid)
returns table (points integer, new_weeks integer, total_weeks integer)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_last    timestamptz;
    v_applied integer;
    v_total   integer;
    v_balance integer;
    v_min     integer := public._game_int('decay_min_points', 5);
    v_first   numeric := 1 - public._game_int('decay_first_week_pct', 3) / 100.0;
    v_weekly  numeric := 1 - public._game_int('decay_weekly_pct', 5) / 100.0;
    v_factor  numeric;
begin
    select p.last_active_at, p.decay_weeks_applied into v_last, v_applied
    from public.profiles p where p.id = p_user;
    if not found then
        return query select 0, 0, 0;
        return;
    end if;
    v_total := floor(extract(epoch from (now() - v_last)) / 604800)::integer;
    if v_total <= v_applied then
        return query select 0, 0, v_total;
        return;
    end if;
    v_balance := public._balance(p_user);
    if v_balance <= v_min then
        return query select 0, v_total - v_applied, v_total;      -- nothing to take
        return;
    end if;
    -- week 1 = first %, every later week = weekly %; only the weeks not yet applied
    v_factor := case when v_applied = 0
                     then v_first * power(v_weekly, v_total - 1)
                     else power(v_weekly, v_total - v_applied) end;
    return query select v_balance - greatest(v_min, round(v_balance * v_factor)::integer),
                        v_total - v_applied, v_total;
end
$$;

create or replace function public._current_balance(p_user uuid)
returns integer
language sql
stable
security definer
set search_path = ''
as $$
    select public._balance(p_user) - (select d.points from public._decay_due(p_user) d);
$$;

-- {earned_points, balance}: the balance now includes the decay due
create or replace function public._points_summary(p_user uuid)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
    select jsonb_build_object('earned_points', public._total_points(p_user),
                              'balance',       public._current_balance(p_user));
$$;

-- Record the decay due (if any). Caller holds the per-user shop lock.
-- Returns {points, weeks}: points taken now, weeks without use in total.
create or replace function public._settle_decay(p_user uuid)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_due record;
begin
    select * into v_due from public._decay_due(p_user);
    if v_due.new_weeks > 0 then
        if v_due.points > 0 then
            insert into public.point_decay (user_id, points, weeks, from_balance)
            values (p_user, v_due.points, v_due.total_weeks, public._balance(p_user));
        end if;
        update public.profiles set decay_weeks_applied = v_due.total_weeks
         where id = p_user;
    end if;
    return jsonb_build_object('points', coalesce(v_due.points, 0),
                              'weeks', coalesce(v_due.total_weeks, 0));
end
$$;

revoke execute on function public._decayed_points(uuid), public._balance(uuid),
                           public._decay_due(uuid), public._current_balance(uuid),
                           public._points_summary(uuid), public._settle_decay(uuid)
    from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- touch_activity - a login: record the decay due, then restart the clock.
-- Answers get_my_status() + {status: 'active', decayed_points, inactive_weeks}.
-- ---------------------------------------------------------------------------
create or replace function public.touch_activity()
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_user  uuid := auth.uid();
    v_decay jsonb;
begin
    if v_user is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;
    perform pg_advisory_xact_lock(hashtext('shop:' || v_user::text));
    v_decay := public._settle_decay(v_user);
    update public.profiles
       set last_active_at = now(), decay_weeks_applied = 0
     where id = v_user;
    return public.get_my_status()
           || jsonb_build_object('status', 'active',
                                 'decayed_points', (v_decay ->> 'points')::integer,
                                 'inactive_weeks', (v_decay ->> 'weeks')::integer);
end
$$;

revoke execute on function public.touch_activity() from public, anon, authenticated;
grant execute on function public.touch_activity() to authenticated;

-- ---------------------------------------------------------------------------
-- get_my_status - balance with the decay due; last use and the last decay
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
        'earned_points', v_total,
        'balance', public._current_balance(v_user),
        'purchases', public._my_purchases(v_user),
        'last_active_at', (select p.last_active_at from public.profiles p
                           where p.id = v_user),
        'last_decay', (select jsonb_build_object('points', d.points, 'weeks', d.weeks,
                                                 'decayed_at', d.decayed_at)
                       from public.point_decay d where d.user_id = v_user
                       order by d.decayed_at desc limit 1),
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

-- ---------------------------------------------------------------------------
-- shop_buy - record the decay due first, so the price is paid from the real balance
-- (same body as in ..._shop.sql plus the _settle_decay line)
-- ---------------------------------------------------------------------------
create or replace function public.shop_buy(p_item text)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_user    uuid := auth.uid();
    v_item    public.shop_items%rowtype;
    v_badge   text;
    v_balance integer;
    v_status  text;
    v_extra   jsonb := '{}'::jsonb;
begin
    if v_user is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;

    select * into v_item from public.shop_items si where si.code = p_item;
    if not found then
        return jsonb_build_object('status', 'unknown_item', 'item', p_item);
    end if;

    -- one purchase at a time per user: the balance cannot be spent twice
    perform pg_advisory_xact_lock(hashtext('shop:' || v_user::text));
    perform public._settle_decay(v_user);

    select coalesce(gc.value #>> '{}', 'breg') into v_badge
    from public.game_config gc where gc.key = 'shop_required_badge';
    v_badge := coalesce(v_badge, 'breg');
    v_balance := public._balance(v_user);

    if exists (select 1 from public.purchases pu
               where pu.user_id = v_user and pu.item_code = v_item.code) then
        v_status := 'already_owned';
    elsif not exists (select 1 from public.user_badges ub
                      where ub.user_id = v_user and ub.badge_code = v_badge) then
        v_status := 'badge_required';
        v_extra := jsonb_build_object('badge', v_badge);
    elsif v_item.requires is not null and not exists (
            select 1 from public.purchases pu
            where pu.user_id = v_user and pu.item_code = v_item.requires) then
        v_status := 'requires_item';
        v_extra := jsonb_build_object('requires', v_item.requires);
    elsif v_balance < v_item.price then
        v_status := 'not_enough_points';
        v_extra := jsonb_build_object('missing', v_item.price - v_balance);
    else
        insert into public.purchases (user_id, item_code, price_paid)
        values (v_user, v_item.code, v_item.price);
        v_status := 'bought';
    end if;

    return public.get_my_status()
           || jsonb_build_object('status', v_status, 'item', v_item.code,
                                 'price', v_item.price)
           || v_extra;
end
$$;

revoke execute on function public.shop_buy(text) from public, anon, authenticated;
grant execute on function public.shop_buy(text) to authenticated;

-- ---------------------------------------------------------------------------
-- export_my_data - also the decay rows (the profile already carries last_active_at)
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
                        'email', u.email,
                        'created_at', u.created_at,
                        'email_confirmed_at', u.email_confirmed_at,
                        'last_sign_in_at', u.last_sign_in_at)
                    from auth.users u where u.id = v_user),
        'profile', (select to_jsonb(p) from public.profiles p where p.id = v_user),
        'point_events', (select coalesce(jsonb_agg(to_jsonb(e) - 'user_id' order by e.created_at),
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
                        from public.point_decay d where d.user_id = v_user))
        || public._points_summary(v_user);
end
$$;

revoke execute on function public.export_my_data() from public, anon, authenticated;
grant execute on function public.export_my_data() to authenticated;

-- ---------------------------------------------------------------------------
-- get_leaderboard - ranked by the current balance (decay due included)
-- ---------------------------------------------------------------------------
drop function if exists public.get_leaderboard(integer);

create function public.get_leaderboard(p_limit integer default 50)
returns table (rank bigint, username text, country text, total_points bigint,
               top_badge text, earned_points bigint)
language sql
stable
security definer
set search_path = ''
as $$
    with totals as (
        select p.id, p.username, p.country,
               public._total_points(p.id)::bigint     as earned_points,
               public._current_balance(p.id)::bigint  as balance
        from public.profiles p
        where p.show_on_leaderboard
    )
    select rank() over (order by t.balance desc) as rank,
           t.username,
           t.country,
           t.balance,
           (select b.name
            from public.user_badges ub
            join public.badges b on b.code = ub.badge_code
            where ub.user_id = t.id
            order by b.points_required desc
            limit 1) as top_badge,
           t.earned_points
    from totals t
    -- by position: in a RETURNS TABLE function the output names are also parameters
    order by 4 desc, 2
    limit least(greatest(coalesce(p_limit, 50), 1), 200);
$$;

revoke execute on function public.get_leaderboard(integer) from public, anon, authenticated;
grant execute on function public.get_leaderboard(integer) to anon, authenticated;
