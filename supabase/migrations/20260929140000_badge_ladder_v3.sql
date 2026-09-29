-- CWatM GUI - badge ladder v3: 12 badges at 5, 15, 30, 50, 100, 200, 400, 800, 1500,
-- 3000, 5000, 10000 points, from the Breg to the Amazonas.
--
-- breg 5, thames 15, morava 30, inn 50, drava 100, elbe 200, rhine 400,
-- ganges 800 (back in the ladder), danube 1500, mekong 3000, nile 5000,
-- amazonas 10000. Earned badges are re-evaluated against the new thresholds: a
-- badge no longer reached is removed, a newly reached one awarded.

-- 1. the Ganges returns (dropped in v2), between the Rhine and the Danube. Its old
--    sort_order 8 is still free (rhine 7 < 8 < danube 10). The temporary threshold
--    keeps points_required unique until step 2 sets the real one.
insert into public.badges (code, name, river_length_km, points_required, sort_order,
                           description)
values ('ganges', 'Ganges', 2525, 1999999, 8, null)
on conflict (code) do nothing;

-- 2. new thresholds - via a temporary range first: points_required is UNIQUE and
--    checked row by row, so moving one badge onto another's old value would
--    collide in the middle of the update.
update public.badges set points_required = 1000000 + sort_order;
update public.badges b
set points_required = v.points
from (values ('breg', 5), ('thames', 15), ('morava', 30), ('inn', 50),
             ('drava', 100), ('elbe', 200), ('rhine', 400), ('ganges', 800),
             ('danube', 1500), ('mekong', 3000), ('nile', 5000),
             ('amazonas', 10000))
     as v(code, points)
where b.code = v.code;

-- 3. re-evaluate every user's badges against the new ladder
delete from public.user_badges ub
using public.badges b
where b.code = ub.badge_code
  and b.points_required > public._total_points(ub.user_id);

insert into public.user_badges (user_id, badge_code)
select t.user_id, b.code
from (select user_id, sum(points)::integer as total
      from public.point_events group by user_id) t
join public.badges b on b.points_required <= t.total
on conflict do nothing;
