-- CWatM GUI - take a reward back, so it can be earned again (testing the reward;
-- Preferences ▸ Account ▸ "Reset MODFLOW reward").
--
-- Removes ONLY the caller's own purchases of the reward's items that were GIVEN
-- (granted, 0 points) - never a bought item, never anyone else's. No points change.
-- Answers get_my_status() merged with {status, reward, items}:
--   status: reset (items = what was removed) | not_owned | unknown_reward

create or replace function public.reset_reward(p_reward text)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_user    uuid := auth.uid();
    v_removed jsonb;
begin
    if v_user is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;
    if not exists (select 1 from public.shop_items si where si.reward = p_reward) then
        return jsonb_build_object('status', 'unknown_reward', 'reward', p_reward);
    end if;

    perform pg_advisory_xact_lock(hashtext('shop:' || v_user::text));
    with removed as (
        delete from public.purchases pu
        using public.shop_items si
        where pu.user_id = v_user
          and pu.item_code = si.code
          and si.reward = p_reward
          and pu.granted
          and pu.price_paid = 0
        returning pu.item_code
    )
    select coalesce(jsonb_agg(item_code), '[]'::jsonb) into v_removed from removed;

    return public.get_my_status()
           || jsonb_build_object(
                  'status', case when jsonb_array_length(v_removed) > 0
                                 then 'reset' else 'not_owned' end,
                  'reward', p_reward,
                  'items', v_removed);
end
$$;

revoke execute on function public.reset_reward(text) from public, anon, authenticated;
grant execute on function public.reset_reward(text) to authenticated;
