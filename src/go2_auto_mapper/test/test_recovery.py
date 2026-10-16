import math

from types import SimpleNamespace

from go2_auto_mapper.recovery import choose_recovery, swept_clear, scan_covers_move
from test_obstacle_sensing import make_grid


def test_rear_blocked_selects_side():
    grid = make_grid(obstacles=[(-1, -.6, -.4, .4)])
    dx, dy = choose_recovery(grid, 0, 0, 0, .3)
    assert dx == 0 and abs(dy) == .3


def test_side_translation_checks_long_body():
    grid = make_grid(obstacles=[(-.45, -.35, .4, .5)])
    assert not swept_clear(grid, 0, 0, 0, 0, .3)
    assert swept_clear(grid, 0, 0, 0, 0, -.3)


def test_unknown_and_off_grid_are_unsafe():
    grid = make_grid()
    grid.data[:] = [-1] * len(grid.data)
    assert choose_recovery(grid, 0, 0, 0, .3) is None
    assert not swept_clear(make_grid(), 2.9, 0, 0, .3, 0)


def test_boxed_in_stays_stopped():
    grid = make_grid(obstacles=[(-1, -.6, -1, 1),
                                (-1, 1, .4, 1), (-1, 1, -1, -.4)])
    assert choose_recovery(grid, 0, 0, 0, .3) is None


def test_rotated_footprint_and_new_obstacle():
    assert swept_clear(make_grid(), 0, 0, math.pi/2, -.3, 0)
    assert not swept_clear(make_grid(obstacles=[(-.3, .3, -.9, -.6)]),
                           0, 0, math.pi/2, -.3, 0)


def test_scan_coverage_requires_measured_free_space():
    scan = SimpleNamespace(angle_min=-math.pi, angle_increment=math.pi/180,
                           range_min=.1, range_max=10., ranges=[5.] * 361)
    assert scan_covers_move(scan, -.3, 0)
    scan.ranges[0] = .55
    assert not scan_covers_move(scan, -.3, 0)
    scan.ranges = [float('inf')] * 361
    assert not scan_covers_move(scan, 0, .3)
