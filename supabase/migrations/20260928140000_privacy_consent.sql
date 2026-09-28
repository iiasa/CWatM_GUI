-- CWatM GUI gamification - record the privacy consent (step S6).
--
-- Every new account must carry the version of the privacy notice the user agreed to
-- (sign-up metadata `privacy_version`, sent by the GUI when "I agree that these data
-- are stored" is ticked). The server refuses a sign-up without it, so the consent
-- cannot be skipped by calling the API directly. Version + time end up in the
-- profile - and therefore in export_my_data() - as the proof of consent.
--
-- Accounts created before this migration keep NULL (they agreed to the short text
-- in the GUI; they are asked again when a new notice version is introduced).

alter table public.profiles
    add column privacy_version     text check (char_length(privacy_version) <= 40),
    add column privacy_accepted_at timestamptz;

-- Not user-editable: the column grants on profiles stay as they were (username,
-- full_name, country, institute, show_on_leaderboard only).

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    md      jsonb := coalesce(new.raw_user_meta_data, '{}'::jsonb);
    version text  := nullif(btrim(md ->> 'privacy_version'), '');
begin
    if version is null then
        raise exception 'privacy consent missing'
            using errcode = '23514',
                  hint = 'Sign-up needs options.data.privacy_version';
    end if;
    insert into public.profiles (id, username, full_name, country, institute,
                                 privacy_version, privacy_accepted_at)
    values (new.id,
            btrim(md ->> 'username'),
            nullif(btrim(md ->> 'full_name'), ''),
            nullif(btrim(md ->> 'country'), ''),
            nullif(btrim(md ->> 'institute'), ''),
            left(version, 40),
            now());
    return new;
end
$$;

revoke execute on function public.handle_new_user() from public, anon, authenticated;
