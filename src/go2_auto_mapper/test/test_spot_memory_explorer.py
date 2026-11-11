"""ROS-dependent tests of the explorer's spot memory; run in the Humble container."""

from types import SimpleNamespace

from go2_auto_mapper.explorer import FrontierExplorer
from go2_auto_mapper.spot_memory import Spot, SpotMemory

# A 10 m x 10 m map of free space at 0.1 m per cell, origin at (0, 0).
RESOLUTION = 0.1
SIZE = 100


def free_map():
    return SimpleNamespace(
        info=SimpleNamespace(
            resolution=RESOLUTION, width=SIZE, height=SIZE,
            origin=SimpleNamespace(position=SimpleNamespace(x=0.0, y=0.0))),
        data=[0] * (SIZE * SIZE))


def explorer_stub(position=(5.0, 5.0), use_spot_memory=True, blacklisted=()):
    messages, goals = [], []
    node = SimpleNamespace(
        map=free_map(), use_spot_memory=use_spot_memory,
        spot_memory=SpotMemory(size=10, min_clearance=0.8),
        escape_spot=None, escape_skip_memory=False, escape_pending=False,
        last_escape_time=None, open_space_clearance=0.8, goal_is_escape=False,
        goal_frontier=None, consecutive_failures=0, stuck_failure_count=3,
        latest_scan=None, messages=messages, goals=goals,
    )
    logger = SimpleNamespace(info=lambda m, **k: messages.append(m),
                             warn=lambda m, **k: messages.append(m))
    node.get_logger = lambda: logger
    node.get_robot_position = lambda: position
    node.world_to_grid = lambda x, y: (x / RESOLUTION, y / RESOLUTION)
    node.grid_to_world = lambda gx, gy: ((gx + 0.5) * RESOLUTION, (gy + 0.5) * RESOLUTION)
    node.is_goal_blacklisted = lambda x, y: (x, y) in blacklisted
    node.emit_goal_outcome = lambda *args: None
    node.blacklist_current_goal = lambda: None

    def send_goal(x, y, is_escape=False):
        goals.append((x, y, is_escape))
        node.goal_is_escape = is_escape
        return True

    node.send_goal = send_goal
    node.spot_still_open = lambda spot: FrontierExplorer.spot_still_open(node, spot)
    node.request_escape = lambda reason: FrontierExplorer.request_escape(node, reason)
    node.log_event = lambda m: None
    return node


def test_escape_goes_back_to_the_last_scanned_spot_first():
    node = explorer_stub()
    node.spot_memory.remember(2.0, 2.0, clearance=1.0, stamp=1.0)
    node.spot_memory.remember(7.0, 7.0, clearance=1.0, stamp=2.0)
    FrontierExplorer.start_escape(node)
    assert node.goals == [(7.0, 7.0, True)]
    assert node.escape_spot == Spot(7.0, 7.0, 1.0, 2.0)


def test_escape_skips_a_remembered_spot_that_is_now_blocked_on_the_map():
    node = explorer_stub()
    node.spot_memory.remember(2.0, 2.0, clearance=1.0, stamp=1.0)
    node.spot_memory.remember(7.0, 7.0, clearance=1.0, stamp=2.0)
    node.map.data[70 * SIZE + 72] = 100   # a new obstacle 0.2 m from (7, 7)
    FrontierExplorer.start_escape(node)
    assert node.goals == [(2.0, 2.0, True)]


def test_escape_skips_a_blacklisted_spot():
    node = explorer_stub(blacklisted={(7.0, 7.0)})
    node.spot_memory.remember(7.0, 7.0, clearance=1.0, stamp=2.0)
    FrontierExplorer.start_escape(node)
    assert node.escape_spot is None
    assert node.goals and node.goals[0][:2] != (7.0, 7.0)   # nearest open space instead


def test_escape_without_memory_uses_the_nearest_open_space():
    node = explorer_stub(use_spot_memory=False)
    node.spot_memory.remember(7.0, 7.0, clearance=1.0, stamp=2.0)
    FrontierExplorer.start_escape(node)
    assert node.escape_spot is None
    assert node.goals and node.goals[0][:2] != (7.0, 7.0)


def test_failing_to_reach_the_spot_forgets_it_and_falls_back_to_open_space():
    node = explorer_stub()
    node.spot_memory.remember(7.0, 7.0, clearance=1.0, stamp=2.0)
    FrontierExplorer.start_escape(node)
    FrontierExplorer.record_goal_failure(node)
    assert node.spot_memory.spots == ()
    assert node.escape_spot is None
    assert node.escape_pending   # the loop runs start_escape again
    FrontierExplorer.start_escape(node)
    assert len(node.goals) == 2 and node.goals[1][:2] != (7.0, 7.0)
    assert not node.escape_skip_memory   # only that one fallback skips memory


def test_failing_the_open_space_fallback_just_carries_on_exploring():
    node = explorer_stub()
    node.goal_is_escape = True
    FrontierExplorer.record_goal_failure(node)
    assert not node.escape_pending
    assert any('carrying on exploring' in m for m in node.messages)


def test_a_finished_scan_with_room_is_remembered():
    node = explorer_stub(position=(3.0, 4.0))
    node.latest_scan = SimpleNamespace(ranges=[1.5, 2.0, 0.9], range_min=0.1, range_max=10.0)
    FrontierExplorer.remember_scan_spot(node)
    assert [(s.x, s.y, s.clearance) for s in node.spot_memory.spots] == [(3.0, 4.0, 0.9)]


def test_a_finished_scan_in_a_tight_spot_is_not_remembered():
    node = explorer_stub()
    node.latest_scan = SimpleNamespace(ranges=[1.5, 0.4], range_min=0.1, range_max=10.0)
    FrontierExplorer.remember_scan_spot(node)
    assert node.spot_memory.spots == ()
