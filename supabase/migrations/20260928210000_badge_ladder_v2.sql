-- CWatM GUI - new badge ladder: 11 badges at 5, 10, 25, 50, 100, 250, 500, 1000, 2500,
-- 5000, 10000 points, from the Breg to the Amazonas.
--
-- Kept (new threshold): breg 5, thames 10, morava 25, inn 50, drava 100, elbe 250,
-- rhine 500, danube 1000, mekong 2500, nile 5000, amazonas 10000.
-- Dropped: ganges, zambezi, indus, mississippi, congo, yellow, yangtze.
-- Earned badges are re-evaluated against the new thresholds: a badge no longer
-- reached is removed, a newly reached one awarded.

-- 1. dropped rivers (their earned rows first - user_badges references badges.code)
delete from public.user_badges
where badge_code in ('ganges', 'zambezi', 'indus', 'mississippi', 'congo',
                     'yellow', 'yangtze');
delete from public.badges
where code in ('ganges', 'zambezi', 'indus', 'mississippi', 'congo',
               'yellow', 'yangtze');

-- 2. new thresholds - via a temporary range first: points_required is UNIQUE and
--    checked row by row, so moving e.g. thames 5 -> 10 would collide with morava's
--    old 10 in the middle of the update.
update public.badges set points_required = 1000000 + sort_order;
update public.badges b
set points_required = v.points
from (values ('breg', 5), ('thames', 10), ('morava', 25), ('inn', 50),
             ('drava', 100), ('elbe', 250), ('rhine', 500), ('danube', 1000),
             ('mekong', 2500), ('nile', 5000), ('amazonas', 10000))
     as v(code, points)
where b.code = v.code;

-- (description of the first badge: it now takes 5 points, not one run)
update public.badges
set description = 'Your first 5 points - where the Danube begins.'
where code = 'breg';

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
