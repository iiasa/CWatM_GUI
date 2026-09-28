-- CWatM GUI gamification - rules + river badge ladder (step S1).
-- Plain data: change a threshold or add a river with an UPDATE/INSERT, no client
-- release needed. Lengths are approximate (sources differ) and only for display.

insert into public.game_config (key, value, description) values
    ('points_per_run',       '1',  'Points for one full CWatM run'),
    ('min_timesteps',        '30', 'A run must cover at least this many timesteps to count (0 = no minimum)'),
    ('daily_run_cap',        '20', 'At most this many run awards per user in 24 h (0 = no cap)'),
    ('login_max_failures',   '10', 'Failed username logins before the login is throttled'),
    ('login_window_minutes', '15', 'Window for login_max_failures, in minutes')
on conflict (key) do nothing;

-- From the Breg (a source river of the Danube) to the Amazonas. Mostly ordered by
-- length; the Amazonas closes the ladder as the largest river by discharge.
insert into public.badges (code, name, river_length_km, points_required, sort_order, description) values
    ('breg',        'Breg',          49,    1,  1, 'Your first full CWatM run - where the Danube begins.'),
    ('thames',      'Thames',       346,    5,  2, null),
    ('morava',      'Morava',       354,   10,  3, 'The river of the CWatM example basin.'),
    ('inn',         'Inn',          517,   20,  4, null),
    ('drava',       'Drava',        710,   35,  5, null),
    ('elbe',        'Elbe',        1094,   50,  6, null),
    ('rhine',       'Rhine',       1233,   75,  7, null),
    ('ganges',      'Ganges',      2525,  100,  8, null),
    ('zambezi',     'Zambezi',     2574,  150,  9, null),
    ('danube',      'Danube',      2850,  200, 10, null),
    ('indus',       'Indus',       3180,  300, 11, null),
    ('mississippi', 'Mississippi', 3730,  400, 12, null),
    ('mekong',      'Mekong',      4350,  500, 13, null),
    ('congo',       'Congo',       4700,  750, 14, null),
    ('yellow',      'Yellow River',5464, 1000, 15, null),
    ('yangtze',     'Yangtze',     6300, 1500, 16, null),
    ('nile',        'Nile',        6650, 2000, 17, null),
    ('amazonas',    'Amazonas',    6400, 3000, 18, 'The largest river on Earth by discharge.')
on conflict (code) do nothing;
