-- CWatM GUI - the Shop's second animal set (the sparkline animals are now images,
-- assets/ani/*.png) and the first REWARD item: the mole.
--
--   trout 10, catfish 30, otter 20, clownfish 30, beaver 30, octopus 20, bottle 2
--   mole  - not for sale: given once, as the reward for the first successful run
--           with coupled MODFLOW (claim_reward('modflow_first_run')).
--
-- fish -> trout and sailboat -> bottle are RENAMED, not replaced: purchases.item_code
-- references shop_items(code) "on update cascade", so whoever bought the fish now
-- owns the trout and the sailboat owner the bottle - nothing bought is lost.
--
-- shop_items.reward: null = for sale (shop_buy); a reward code = only ever given by
-- claim_reward(), never sold. get_shop_items() lists only what is for sale, so older
-- GUIs never offer the mole; shop_buy() refuses a reward item ('reward_only').
--
-- The claim cannot be verified by the server (it does not see the run), like the
-- Cheat it only opens an animal - no points are involved (price_paid 0, granted).

alter table public.shop_items add column reward text
    check (reward is null or reward ~ '^[a-z0-9_]{2,40}$');

-- the renames (cascade to purchases) - sort_order is unique, so free 110/140 first
update public.shop_items set code = 'trout',  name = 'Trout',  price = 10 where code = 'fish';
update public.shop_items set code = 'bottle', name = 'Bottle', price = 2  where code = 'sailboat';
update public.shop_items set price = 20 where code = 'otter';
update public.shop_items set price = 30 where code = 'beaver';
update public.shop_items set price = 20 where code = 'octopus';

insert into public.shop_items (code, kind, name, price, requires, sort_order, reward) values
    ('catfish',   'animal', 'Catfish',   30, null, 112, null),
    ('clownfish', 'animal', 'Clownfish', 30, null, 114, null),
    ('mole',      'animal', 'Mole',       0, null, 160, 'modflow_first_run')
on conflict (code) do nothing;

-- ---------------------------------------------------------------------------
-- get_shop_items - the price list: only what is for sale
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
    where si.reward is null
    order by si.sort_order;
$$;

revoke execute on function public.get_shop_items() from public, anon, authenticated;
grant execute on function public.get_shop_items() to anon, authenticated;

-- ---------------------------------------------------------------------------
-- shop_buy - same body as in ..._point_decay.sql plus the reward_only refusal
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
    if v_item.reward is not null then
        return jsonb_build_object('status', 'reward_only', 'item', v_item.code);
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
-- claim_reward - give the item(s) of a reward, once. Answers get_my_status()
-- merged with {status, reward, items}:
--   status: granted (items = what was given now) | already_owned | unknown_reward
-- ---------------------------------------------------------------------------
create or replace function public.claim_reward(p_reward text)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_user  uuid := auth.uid();
    v_given jsonb;
begin
    if v_user is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;
    if not exists (select 1 from public.shop_items si where si.reward = p_reward) then
        return jsonb_build_object('status', 'unknown_reward', 'reward', p_reward);
    end if;

    perform pg_advisory_xact_lock(hashtext('shop:' || v_user::text));
    with given as (
        insert into public.purchases (user_id, item_code, price_paid, granted)
        select v_user, si.code, 0, true
        from public.shop_items si
        where si.reward = p_reward
        on conflict do nothing
        returning item_code
    )
    select coalesce(jsonb_agg(item_code), '[]'::jsonb) into v_given from given;

    return public.get_my_status()
           || jsonb_build_object(
                  'status', case when jsonb_array_length(v_given) > 0
                                 then 'granted' else 'already_owned' end,
                  'reward', p_reward,
                  'items', v_given);
end
$$;

revoke execute on function public.claim_reward(text) from public, anon, authenticated;
grant execute on function public.claim_reward(text) to authenticated;
