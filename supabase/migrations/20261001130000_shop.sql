-- CWatM GUI - the Shop (see shop.md, Step 2).
--
-- Points are split into two numbers, both COMPUTED (never stored), so they cannot
-- drift apart from the tables they come from:
--
--   earned points  = sum(point_events.points)   - never goes down; decides the
--                    badges (_award_badges is unchanged and keeps using
--                    _total_points = earned); also "the maximum ever achieved".
--   balance        = earned - sum(purchases.price_paid)  - what can be spent; the
--                    "actual points" the leaderboard ranks by (decision 4).
--
-- Spending never takes a badge away; a new badge still needs its full earned points.
--
--   shop_items   what can be bought (levels + sparkline animals); prices live here,
--                so they can change without a new GUI release. Public.
--   purchases    one row per user and item (nothing is bought twice). Read-own;
--                written ONLY by shop_buy() and by the grandfathering below.
--   shop_buy()   the only way to buy: Breg badge, balance, not owned yet, and the
--                item's prerequisite (Expert needs Advanced) - all checked under a
--                per-user lock, so two quick clicks can never overspend.
--
-- award_run() and academy_complete_level() are wrapped (renamed to *_core, their
-- logic untouched) so their answers also carry earned_points + balance. A later
-- migration that changes their logic must replace the *_core function, not the
-- wrapper.

-- ---------------------------------------------------------------------------
-- shop_items
-- ---------------------------------------------------------------------------
create table public.shop_items (
    code       text primary key check (code ~ '^[a-z0-9_]{2,40}$'),
    kind       text not null check (kind in ('level', 'animal')),
    name       text not null,
    price      integer not null check (price >= 0),
    -- an item that must be owned first (Expert -> Advanced)
    requires   text references public.shop_items (code) on update cascade,
    sort_order integer not null unique
);

insert into public.shop_items (code, kind, name, price, requires, sort_order) values
    ('advanced', 'level',  'Advanced', 20, null,       10),
    ('expert',   'level',  'Expert',   40, 'advanced', 20),
    ('fish',     'animal', 'Fish',      5, null,       110),
    ('otter',    'animal', 'Otter',    10, null,       120),
    ('beaver',   'animal', 'Beaver',   20, null,       130),
    ('sailboat', 'animal', 'Sailboat', 30, null,       140),
    ('octopus',  'animal', 'Octopus',  50, null,       150);

-- the badge that opens the shop
insert into public.game_config (key, value, description) values
    ('shop_required_badge', '"breg"', 'Badge a user needs before the Shop sells anything')
on conflict (key) do nothing;

-- ---------------------------------------------------------------------------
-- purchases
-- ---------------------------------------------------------------------------
create table public.purchases (
    user_id      uuid not null references auth.users (id) on delete cascade,
    item_code    text not null references public.shop_items (code) on update cascade,
    price_paid   integer not null check (price_paid >= 0),
    -- true = given for free (existing accounts kept their levels), not bought
    granted      boolean not null default false,
    purchased_at timestamptz not null default now(),
    primary key (user_id, item_code)
);

revoke all on table public.shop_items, public.purchases from anon, authenticated;
alter table public.shop_items enable row level security;
alter table public.purchases  enable row level security;

grant select on public.shop_items to anon, authenticated;
create policy "shop_items: read all" on public.shop_items
    for select to anon, authenticated using (true);

-- read your own; no insert/update/delete policy, so only shop_buy() writes
grant select on public.purchases to authenticated;
create policy "purchases: read own" on public.purchases
    for select to authenticated
    using ((select auth.uid()) = user_id);

-- ---------------------------------------------------------------------------
-- point helpers
-- ---------------------------------------------------------------------------
create or replace function public._spent_points(p_user uuid)
returns integer
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(sum(pu.price_paid), 0)::integer
    from public.purchases pu
    where pu.user_id = p_user;
$$;

create or replace function public._balance(p_user uuid)
returns integer
language sql
stable
security definer
set search_path = ''
as $$
    select public._total_points(p_user) - public._spent_points(p_user);
$$;

-- {earned_points, balance} - merged into every answer that changes points
create or replace function public._points_summary(p_user uuid)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
    select jsonb_build_object('earned_points', public._total_points(p_user),
                              'balance',       public._balance(p_user));
$$;

create or replace function public._my_purchases(p_user uuid)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce(jsonb_agg(jsonb_build_object(
               'code',         si.code,
               'kind',         si.kind,
               'name',         si.name,
               'price_paid',   pu.price_paid,
               'granted',      pu.granted,
               'purchased_at', pu.purchased_at) order by si.sort_order),
           '[]'::jsonb)
    from public.purchases pu
    join public.shop_items si on si.code = pu.item_code
    where pu.user_id = p_user;
$$;

revoke execute on function public._spent_points(uuid), public._balance(uuid),
                           public._points_summary(uuid), public._my_purchases(uuid)
    from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- grandfathering (decision 1): every account that exists now keeps Advanced and
-- Expert - free, so their balance is untouched. Accounts created later buy them.
-- ---------------------------------------------------------------------------
insert into public.purchases (user_id, item_code, price_paid, granted)
select p.id, l.code, 0, true
from public.profiles p
cross join (values ('advanced'), ('expert')) as l(code)
on conflict do nothing;

-- ---------------------------------------------------------------------------
-- get_my_status - adds earned_points, balance, purchases. total_points keeps its
-- meaning (= earned) for older GUIs; next_badge stays on earned points.
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
        'balance', public._balance(v_user),
        'purchases', public._my_purchases(v_user),
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
-- get_shop_items - the price list (public)
-- ---------------------------------------------------------------------------
create or replace function public.get_shop_items()
returns table (code text, kind text, name text, price integer, requires text)
language sql
stable
security definer
set search_path = ''
as $$
    select si.code, si.kind, si.name, si.price, si.requires
    from public.shop_items si
    order by si.sort_order;
$$;

revoke execute on function public.get_shop_items() from public, anon, authenticated;
grant execute on function public.get_shop_items() to anon, authenticated;

-- ---------------------------------------------------------------------------
-- shop_buy - the only way to buy. Answers {status, item, price} merged with the
-- caller's full get_my_status(), so the GUI refreshes in one round trip.
--   status: bought | unknown_item | already_owned | badge_required |
--           requires_item (+ requires) | not_enough_points (+ missing)
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
-- award_run / academy_complete_level: their answers also carry earned_points +
-- balance. The existing logic is kept verbatim by renaming it to *_core and
-- wrapping it (auth.uid() reads the request's JWT, so it is the same inside).
-- ---------------------------------------------------------------------------
alter function public.award_run(text, jsonb) rename to _award_run_core;
revoke execute on function public._award_run_core(text, jsonb)
    from public, anon, authenticated;

create function public.award_run(p_run_uid text, p_meta jsonb default '{}'::jsonb)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_result jsonb := public._award_run_core(p_run_uid, p_meta);
begin
    if auth.uid() is null or not (v_result ? 'total_points') then
        return v_result;
    end if;
    return v_result || public._points_summary(auth.uid());
end
$$;

revoke execute on function public.award_run(text, jsonb) from public, anon, authenticated;
grant execute on function public.award_run(text, jsonb) to authenticated;

alter function public.academy_complete_level(integer) rename to _academy_complete_level_core;
revoke execute on function public._academy_complete_level_core(integer)
    from public, anon, authenticated;

create function public.academy_complete_level(p_level integer)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_result jsonb := public._academy_complete_level_core(p_level);
begin
    if auth.uid() is null or not (v_result ? 'total_points') then
        return v_result;
    end if;
    return v_result || public._points_summary(auth.uid());
end
$$;

revoke execute on function public.academy_complete_level(integer) from public, anon, authenticated;
grant execute on function public.academy_complete_level(integer) to authenticated;

-- ---------------------------------------------------------------------------
-- export_my_data - now also the purchases
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
                      from public.purchases pu where pu.user_id = v_user))
        || public._points_summary(v_user);
end
$$;

revoke execute on function public.export_my_data() from public, anon, authenticated;
grant execute on function public.export_my_data() to authenticated;

-- ---------------------------------------------------------------------------
-- get_leaderboard - ranked by the ACTUAL points (balance, decision 4).
-- total_points keeps its column name (older GUIs show it) but is now the balance;
-- earned_points is added; the highest badge still comes from earned points.
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
               public._total_points(p.id)::bigint as earned_points,
               public._balance(p.id)::bigint      as balance
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
