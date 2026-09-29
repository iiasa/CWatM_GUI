-- CWatM GUI - the Register form's visibility choices are stored at sign-up.
--
-- The Register tab now offers, pre-ticked (default YES in the GUI):
--   * Show me on the leaderboard           -> profiles.show_on_leaderboard
--   * Show my location on the world map    -> profiles.show_location_on_map
-- (next to the run-location consent share_locations, which was already read here).
-- The column defaults stay FALSE: a sign-up whose metadata lacks a key (an older
-- GUI) keeps the previous opt-in behaviour. Only the trigger changes.

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    md      jsonb := coalesce(new.raw_user_meta_data, '{}'::jsonb);
    version text  := nullif(btrim(md ->> 'privacy_version'), '');
    share   boolean := coalesce((md ->> 'share_locations')::boolean, false);
    board   boolean := coalesce((md ->> 'show_on_leaderboard')::boolean, false);
    on_map  boolean := coalesce((md ->> 'show_location_on_map')::boolean, false);
    v_lat   numeric := case when md ->> 'location_lat' ~ '^-?\d{1,3}(\.\d+)?$'
                            then round((md ->> 'location_lat')::numeric, 3) end;
    v_lon   numeric := case when md ->> 'location_lon' ~ '^-?\d{1,3}(\.\d+)?$'
                            then round((md ->> 'location_lon')::numeric, 3) end;
begin
    if version is null then
        raise exception 'privacy consent missing'
            using errcode = '23514',
                  hint = 'Sign-up needs options.data.privacy_version';
    end if;
    if v_lat is null or v_lon is null
       or v_lat not between -90 and 90 or v_lon not between -180 and 180 then
        v_lat := null;
        v_lon := null;
    end if;
    insert into public.profiles (id, username, full_name, country, institute,
                                 privacy_version, privacy_accepted_at,
                                 share_locations, share_locations_at,
                                 location_lat, location_lon,
                                 show_on_leaderboard, show_location_on_map)
    values (new.id,
            btrim(md ->> 'username'),
            nullif(btrim(md ->> 'full_name'), ''),
            nullif(btrim(md ->> 'country'), ''),
            nullif(btrim(md ->> 'institute'), ''),
            left(version, 40),
            now(),
            share,
            case when share then now() end,
            v_lat,
            v_lon,
            board,
            on_map);
    return new;
end
$$;

revoke execute on function public.handle_new_user() from public, anon, authenticated;
