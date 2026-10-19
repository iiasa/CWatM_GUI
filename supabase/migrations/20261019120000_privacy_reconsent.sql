-- CWatM GUI gamification - ask existing users to agree again when the privacy notice
-- changes.
--
-- The profile keeps the version of the notice a user agreed to and when
-- (privacy_version / privacy_accepted_at, 20260928140000_privacy_consent.sql), so far
-- written only at sign-up. After every login the GUI reads it (get_privacy_consent)
-- and compares it with the notice it ships (account_config.PRIVACY_VERSION). When they
-- differ, the GUI shows the new notice; "Agree" records the new version here
-- (accept_privacy), "Log out" changes nothing. The notice promises exactly this
-- ("Changes" in documentation/CWatM_Account_Privacy.md).

-- ---------------------------------------------------------------------------
-- get_privacy_consent - the caller's own consent record
-- ---------------------------------------------------------------------------
create or replace function public.get_privacy_consent()
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
    return (select jsonb_build_object('privacy_version', p.privacy_version,
                                      'privacy_accepted_at', p.privacy_accepted_at)
            from public.profiles p where p.id = v_user);
end
$$;
revoke execute on function public.get_privacy_consent() from public, anon, authenticated;
grant execute on function public.get_privacy_consent() to authenticated;

-- ---------------------------------------------------------------------------
-- accept_privacy - the caller agrees to version p_version of the notice
-- ---------------------------------------------------------------------------
-- Only the caller's own row; the version text follows the same rule as at sign-up
-- (non-empty, at most 40 characters - the column's check constraint).
create or replace function public.accept_privacy(p_version text)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_user    uuid := auth.uid();
    v_version text := nullif(btrim(p_version), '');
begin
    if v_user is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;
    if v_version is null or char_length(v_version) > 40 then
        raise exception 'invalid privacy version' using errcode = '23514';
    end if;
    update public.profiles
       set privacy_version = v_version,
           privacy_accepted_at = now()
     where id = v_user;
    return (select jsonb_build_object('privacy_version', p.privacy_version,
                                      'privacy_accepted_at', p.privacy_accepted_at)
            from public.profiles p where p.id = v_user);
end
$$;
revoke execute on function public.accept_privacy(text) from public, anon, authenticated;
grant execute on function public.accept_privacy(text) to authenticated;
