-- CWatM GUI - the CWatM Academy Field Test highscore in the user's profile.
--
-- The Field Test (Level 1: locate the outlet of a random big river basin) keeps a
-- score: +1000 for every basin found, minus the kilometres of every wrong click.
-- The best score is kept here, so it follows the user to any computer.
--
--   profiles.field_test_highscore   the best Field Test score. Written ONLY by
--                                   field_test_submit_score (no column grant), and
--                                   it only ever goes up.
--
-- No points or badges come from the score - it is a game of its own.

alter table public.profiles
    add column field_test_highscore integer not null default 0
        check (field_test_highscore >= 0);

-- ---------------------------------------------------------------------------
-- get_field_test_highscore - {highscore}
-- ---------------------------------------------------------------------------
create or replace function public.get_field_test_highscore()
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
        'highscore', coalesce((select p.field_test_highscore from public.profiles p
                               where p.id = v_user), 0));
end
$$;

revoke execute on function public.get_field_test_highscore() from public, anon, authenticated;
grant execute on function public.get_field_test_highscore() to authenticated;

-- ---------------------------------------------------------------------------
-- field_test_submit_score - keep the better of the stored and the new score
--   {status: new_highscore | kept | invalid_score, highscore}
-- ---------------------------------------------------------------------------
create or replace function public.field_test_submit_score(p_score integer)
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
    select p.field_test_highscore into v_old from public.profiles p where p.id = v_user;
    v_old := coalesce(v_old, 0);
    -- 1000 per basin: a score beyond 10 million is not a played game
    if p_score is null or p_score < 0 or p_score > 10000000 then
        return jsonb_build_object('status', 'invalid_score', 'highscore', v_old);
    end if;

    update public.profiles p
       set field_test_highscore = greatest(p.field_test_highscore, p_score)
     where p.id = v_user
    returning p.field_test_highscore into v_new;

    return jsonb_build_object(
        'status',    case when coalesce(v_new, 0) > v_old then 'new_highscore' else 'kept' end,
        'highscore', coalesce(v_new, v_old));
end
$$;

revoke execute on function public.field_test_submit_score(integer) from public, anon, authenticated;
grant execute on function public.field_test_submit_score(integer) to authenticated;
