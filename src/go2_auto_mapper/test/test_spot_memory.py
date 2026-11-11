import math

from go2_auto_mapper.open_space import has_clearance
from go2_auto_mapper.spot_memory import (
    Spot,
    SpotMemory,
    choose_spot,
    scan_clearance,
    scan_covers_circle,
)


def test_scan_clearance_is_the_closest_valid_return():
    ranges = [2.0, 0.9, math.inf, 0.05, math.nan, 12.0, 1.4]
    assert scan_clearance(ranges, range_min=0.1, range_max=10.0) == 0.9


def test_scan_clearance_of_a_scan_with_no_valid_return_is_unknown():
    assert scan_clearance([math.inf, math.nan, 0.01], 0.1, 10.0) is None


def test_remembers_only_spots_with_enough_room():
    memory = SpotMemory(size=10, min_clearance=0.8)
    assert memory.remember(1.0, 2.0, clearance=1.2, stamp=5.0)
    assert not memory.remember(4.0, 2.0, clearance=0.5, stamp=6.0)
    assert not memory.remember(6.0, 2.0, clearance=None, stamp=7.0)
    assert memory.spots == (Spot(1.0, 2.0, 1.2, 5.0),)


def test_keeps_only_the_most_recent_spots():
    memory = SpotMemory(size=2, min_clearance=0.8)
    for i in range(3):
        memory.remember(float(i * 2), 0.0, clearance=1.0, stamp=float(i))
    assert [s.x for s in memory.spots] == [2.0, 4.0]


def test_a_scan_near_the_last_spot_replaces_it():
    memory = SpotMemory(size=10, min_clearance=0.8)
    memory.remember(1.0, 1.0, clearance=1.0, stamp=1.0)
    memory.remember(1.2, 1.1, clearance=1.5, stamp=2.0)
    assert memory.spots == (Spot(1.2, 1.1, 1.5, 2.0),)


def test_forget_drops_the_spot():
    memory = SpotMemory(size=10, min_clearance=0.8)
    memory.remember(1.0, 1.0, clearance=1.0, stamp=1.0)
    memory.remember(5.0, 1.0, clearance=1.0, stamp=2.0)
    memory.forget(Spot(5.0, 1.0, 1.0, 2.0))
    assert [s.x for s in memory.spots] == [1.0]


def test_choose_spot_takes_the_most_recent_usable_one():
    spots = (Spot(1.0, 0.0, 1.0, 1.0), Spot(3.0, 0.0, 1.0, 2.0), Spot(5.0, 0.0, 1.0, 3.0))
    chosen = choose_spot(spots, (0.0, 0.0), min_move=0.5, usable=lambda s: s.x != 5.0)
    assert chosen == Spot(3.0, 0.0, 1.0, 2.0)


def test_choose_spot_skips_the_spot_the_robot_is_standing_on():
    spots = (Spot(1.0, 0.0, 1.0, 1.0), Spot(0.2, 0.0, 1.0, 2.0))
    chosen = choose_spot(spots, (0.0, 0.0), min_move=0.5, usable=lambda s: True)
    assert chosen == Spot(1.0, 0.0, 1.0, 1.0)


def test_choose_spot_returns_none_when_nothing_is_usable():
    spots = (Spot(1.0, 0.0, 1.0, 1.0),)
    assert choose_spot(spots, (0.0, 0.0), 0.5, usable=lambda s: False) is None
    assert choose_spot((), (0.0, 0.0), 0.5, usable=lambda s: True) is None


def grid(width, height, walls=()):
    data = [0] * (width * height)
    for x, y in walls:
        data[y * width + x] = 100
    return data


def test_has_clearance_needs_free_cells_all_around():
    data = grid(20, 20)
    assert has_clearance(data, 20, 20, (10, 10), clearance=5)
    data = grid(20, 20, walls=[(13, 10)])
    assert not has_clearance(data, 20, 20, (10, 10), clearance=5)
    assert has_clearance(data, 20, 20, (10, 10), clearance=3)


def test_has_clearance_treats_unknown_and_the_map_edge_as_blocked():
    data = grid(20, 20)
    data[10 * 20 + 12] = -1
    assert not has_clearance(data, 20, 20, (10, 10), clearance=4)
    assert not has_clearance(grid(20, 20), 20, 20, (2, 10), clearance=4)


def test_an_obstacle_strike_keeps_the_spot_until_the_second():
    memory = SpotMemory(size=10, min_clearance=0.8)
    memory.remember(1.0, 1.0, clearance=1.0, stamp=1.0)
    memory.remember(5.0, 1.0, clearance=1.0, stamp=2.0)
    spot = memory.spots[-1]
    assert not memory.strike(spot)          # first bump: kept
    assert spot in memory.spots
    assert memory.strike(spot)              # second bump: forgotten
    assert [s.x for s in memory.spots] == [1.0]


def test_strikes_are_counted_per_spot_and_cleared_by_forget():
    memory = SpotMemory(size=10, min_clearance=0.8)
    memory.remember(1.0, 1.0, clearance=1.0, stamp=1.0)
    memory.remember(5.0, 1.0, clearance=1.0, stamp=2.0)
    first, second = memory.spots
    assert not memory.strike(first)
    assert not memory.strike(second)        # a different spot starts at zero
    memory.forget(second)
    memory.remember(5.0, 1.0, clearance=1.0, stamp=2.0)
    assert not memory.strike(memory.spots[-1])   # fresh again after forget


def full_circle_scan(ranges):
    n = len(ranges)
    return dict(angle_min=-math.pi, angle_increment=2 * math.pi / n, ranges=ranges)


def test_a_full_circle_scan_with_a_few_gaps_counts():
    ranges = [2.0] * 360
    ranges[10:20] = [math.nan] * 10
    assert scan_covers_circle(**full_circle_scan(ranges))


def test_a_half_circle_scan_does_not_count():
    assert not scan_covers_circle(-math.pi / 2, math.pi / 180, [2.0] * 180)


def test_a_full_circle_scan_with_many_gaps_does_not_count():
    ranges = [2.0] * 180 + [math.nan] * 180
    assert not scan_covers_circle(**full_circle_scan(ranges))
