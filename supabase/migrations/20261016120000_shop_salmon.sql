-- CWatM GUI - a new sparkline animal for the Shop: the salmon (Jessi),
-- assets/ani/salmon (Jessi).png, for 20 points. Listed with the other fish
-- (trout 110, catfish 112, clownfish 114 - sort_order is unique).

insert into public.shop_items (code, kind, name, price, requires, sort_order, reward) values
    ('salmon', 'animal', 'Salmon', 20, null, 116, null)
on conflict (code) do nothing;
