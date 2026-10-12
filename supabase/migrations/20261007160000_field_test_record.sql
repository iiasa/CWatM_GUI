-- CWatM GUI - the global CWatM Academy Field Test highscore (arcade style).
--
-- Besides every user's own best (profiles.field_test_highscore / _initials), there is
-- ONE highscore for everybody: the best Field Test score of all users and the 2-3
-- initials its holder typed. The GUI shows it as "Highscore: 5000 PB" and the own
-- best as "Your best: n".
--
--   field_test_record   one row (id = true): score, initials, set_at. NO user column
--                       - the record names only the initials, never the account.
--                       Read by everyone (get_field_test_record, anon too); written
--                       only by field_test_submit_score (a login is needed).

create table public.field_test_record (
    id       boolean primary key default true check (id),
    score    integer not null default 0 check (score >= 0),
    initials text check (initials ~ '^[A-Z]{2,3}$'),
    set_at   timestamptz
);

alter table public.field_test_record enable row level security;
-- no policies: only the definer functions below read or write it

-- the best score played so far becomes the first record
insert into public.field_test_record (id, score, initials, set_at)
select true, coalesce(p.field_test_highscore, 0), p.field_test_initials,
       case when p.field_test_highscore > 0 then now() end
  from (select 1) one
  left join lateral (select pr.field_test_highscore, pr.field_test_initials
                       from public.profiles pr
                      order by pr.field_test_highscore desc
                      limit 1) p on true
on conflict (id) do nothing;

-- ---------------------------------------------------------------------------
-- get_field_test_record - {record_score, record_initials} (public)
-- ---------------------------------------------------------------------------
create or replace function public.get_field_test_record()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce((select jsonb_build_object('record_score', r.score,
                                               'record_initials', r.initials)
                     from public.field_test_record r where r.id),
                    jsonb_build_object('record_score', 0, 'record_initials', null));
$$;

revoke execute on function public.get_field_test_record() from public, anon, authenticated;
grant execute on function public.get_field_test_record() to anon, authenticated;

-- ---------------------------------------------------------------------------
-- get_field_test_highscore - own best + the record
--   {highscore, initials, record_score, record_initials}
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
                    jsonb_build_object('highscore', 0, 'initials', null))
           || public.get_field_test_record();
end
$$;

revoke execute on function public.get_field_test_highscore() from public, anon, authenticated;
grant execute on function public.get_field_test_highscore() to authenticated;

-- ---------------------------------------------------------------------------
-- field_test_submit_score - own best and, when beaten, the record
--   {status: new_highscore | kept | invalid_score, highscore, initials,
--    record_status: new_record | kept, record_score, record_initials}
-- ---------------------------------------------------------------------------
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
    v_initials text := upper(btrim(coalesce(p_initials, '')));
    v_row      record;
    v_rec      record;
    v_status   text := 'kept';
    v_rstatus  text := 'kept';
begin
    if v_user is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;
    select p.field_test_highscore, p.field_test_initials into v_row
      from public.profiles p where p.id = v_user;
    -- 1000 per basin: a score beyond 10 million is not a played game
    if p_score is null or p_score < 0 or p_score > 10000000 then
        return jsonb_build_object('status', 'invalid_score',
                                  'highscore', coalesce(v_row.field_test_highscore, 0),
                                  'initials', v_row.field_test_initials)
               || public.get_field_test_record();
    end if;
    if v_initials !~ '^[A-Z]{2,3}$' then
        v_initials := null;
    end if;

    -- the own best
    if p_score > coalesce(v_row.field_test_highscore, 0) then
        update public.profiles p
           set field_test_highscore = p_score,
               field_test_initials  = v_initials
         where p.id = v_user;
        v_status := 'new_highscore';
    end if;

    -- the record of all users (row lock: two records at once cannot both win)
    select r.score, r.initials into v_rec
      from public.field_test_record r where r.id for update;
    if p_score > coalesce(v_rec.score, 0) then
        insert into public.field_test_record as r (id, score, initials, set_at)
        values (true, p_score, v_initials, now())
        on conflict (id) do update
           set score = excluded.score, initials = excluded.initials,
               set_at = excluded.set_at;
        v_rstatus := 'new_record';
    end if;

    return (select jsonb_build_object('status', v_status,
                                      'highscore', p.field_test_highscore,
                                      'initials', p.field_test_initials)
              from public.profiles p where p.id = v_user)
           || jsonb_build_object('record_status', v_rstatus)
           || public.get_field_test_record();
end
$$;

revoke execute on function public.field_test_submit_score(integer, text) from public, anon, authenticated;
grant execute on function public.field_test_submit_score(integer, text) to authenticated;
