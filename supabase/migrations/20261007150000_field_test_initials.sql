-- CWatM GUI - initials next to the CWatM Academy Field Test highscore.
--
-- Beating the highscore asks for 2 to 3 letters (your initials), shown next to
-- it ("Highscore: 5000 PB"), arcade style.
--
--   profiles.field_test_initials   2-3 capital letters, or null. Written ONLY by
--                                  field_test_submit_score (no column grant), and
--                                  only together with a new highscore.

alter table public.profiles
    add column field_test_initials text
        check (field_test_initials ~ '^[A-Z]{2,3}$');

-- ---------------------------------------------------------------------------
-- get_field_test_highscore - {highscore, initials}
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
    return coalesce((select jsonb_build_object('highscore', p.field_test_highscore,
                                               'initials', p.field_test_initials)
                     from public.profiles p where p.id = v_user),
                    jsonb_build_object('highscore', 0, 'initials', null));
end
$$;

revoke execute on function public.get_field_test_highscore() from public, anon, authenticated;
grant execute on function public.get_field_test_highscore() to authenticated;

-- ---------------------------------------------------------------------------
-- field_test_submit_score - now with the initials typed for a new highscore
--   {status: new_highscore | kept | invalid_score, highscore, initials}
-- ---------------------------------------------------------------------------
drop function if exists public.field_test_submit_score(integer);

create or replace function public.field_test_submit_score(p_score integer,
                                                          p_initials text default null)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_user     uuid := auth.uid();
    v_old      integer;
    v_initials text := upper(btrim(coalesce(p_initials, '')));
    v_row      record;
begin
    if v_user is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;
    select p.field_test_highscore, p.field_test_initials into v_row
      from public.profiles p where p.id = v_user;
    v_old := coalesce(v_row.field_test_highscore, 0);
    -- 1000 per basin: a score beyond 10 million is not a played game
    if p_score is null or p_score < 0 or p_score > 10000000 then
        return jsonb_build_object('status', 'invalid_score', 'highscore', v_old,
                                  'initials', v_row.field_test_initials);
    end if;
    if v_initials !~ '^[A-Z]{2,3}$' then
        v_initials := null;
    end if;

    if p_score > v_old then
        update public.profiles p
           set field_test_highscore = p_score,
               field_test_initials  = v_initials
         where p.id = v_user;
        return jsonb_build_object('status', 'new_highscore', 'highscore', p_score,
                                  'initials', v_initials);
    end if;
    return jsonb_build_object('status', 'kept', 'highscore', v_old,
                              'initials', v_row.field_test_initials);
end
$$;

revoke execute on function public.field_test_submit_score(integer, text) from public, anon, authenticated;
grant execute on function public.field_test_submit_score(integer, text) to authenticated;
