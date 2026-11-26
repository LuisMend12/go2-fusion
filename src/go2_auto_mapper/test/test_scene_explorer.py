"""
ROS-dependent tests of vlm_mode 'describe' in the explorer; run in the Humble container.

The scan hands every direction to the ranker, a goal choice never waits for
the models, and only a ready ranking made where the robot stands reorders the
goals.
"""

import math
import time
from types import SimpleNamespace

from go2_auto_mapper.explorer import VIEW_BINS, FrontierExplorer
from go2_auto_mapper.scene_ranking import DirectionRanking


class FakeRanker:
    """Records what the explorer hands over; answers only when told to."""

    def __init__(self, result=None):
        self.started, self.views, self.finished, self.facts = [], [], [], []
        self.result = result

    def start_scan(self, scan_id):
        self.started.append(scan_id)

    def set_facts(self, scan_id, x, y, facts):
        self.facts.append((scan_id, x, y, facts))

    def add_view(self, scan_id, index, frame):
        self.views.append((scan_id, index))

    def finish_scan(self, scan_id, x, y, facts):
        self.finished.append((scan_id, x, y, facts))

    def take_result(self):
        result, self.result = self.result, None
        return result


def explorer_stub(ranker, pose=(0.0, 0.0, 0.0)):
    messages = []
    # 21 x 21 cells around the origin: known on the west half, unknown east.
    width = height = 21
    data = [0 if x < 10 else -1 for y in range(height) for x in range(width)]
    grid = SimpleNamespace(
        info=SimpleNamespace(resolution=0.05, width=width, height=height,
                             origin=SimpleNamespace(position=SimpleNamespace(x=-0.5, y=-0.5))),
        data=data)
    scan = SimpleNamespace(ranges=[2.0] * 360, angle_min=-math.pi,
                           angle_increment=2 * math.pi / 360)
    node = SimpleNamespace(
        scene_ranker=ranker, scene_ranking=None, scene_scan_id=0, scene_scanning=False,
        scene_bins_sent=set(), scene_scan_ended={}, vlm_weight=400.0, map=grid,
        map_frame='map', info_gain_range=0.5, latest_scan=scan, messages=messages,
    )
    logger = SimpleNamespace(
        info=lambda m, **k: messages.append(m), warn=lambda m, **k: messages.append(m))
    node.get_logger = lambda: logger
    node.get_robot_pose = lambda frame: pose
    node.world_to_grid = lambda x, y: FrontierExplorer.world_to_grid(node, x, y)
    node.scene_facts = lambda: FrontierExplorer.scene_facts(node)
    return node


def logged(node, text):
    return sum(text in m for m in node.messages)


# (score, x, y, frontier size); lower is better. The map prefers the west goal.
POOL = [(-100.0, 1.0, 0.0, 5), (-120.0, -1.0, 0.0, 5)]
EAST_OPEN = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def test_scan_hands_every_direction_to_the_ranker():
    ranker = FakeRanker()
    node = explorer_stub(ranker)
    FrontierExplorer.scene_scan_started(node)
    FrontierExplorer.scene_scan_finished(node)
    assert ranker.started == [1]
    scan_id, x, y, facts = ranker.finished[0]
    assert (scan_id, x, y) == (1, 0.0, 0.0)
    assert len(facts) == VIEW_BINS
    # Unknown space lies east only: the east slice sees it, the west one doesn't.
    assert facts[0]['unknown_cells'] > 0
    assert facts[4]['unknown_cells'] == 0
    assert all(f['free_m'] == 2.0 for f in facts)
    assert not node.scene_scanning
    # The facts also went out when the scan started, for an early ranking.
    assert ranker.facts and ranker.facts[0][0] == 1 and len(ranker.facts[0][3]) == VIEW_BINS


def test_a_scan_that_never_started_asks_for_nothing():
    ranker = FakeRanker()
    node = explorer_stub(ranker)
    FrontierExplorer.scene_scan_finished(node)
    assert ranker.finished == []


def test_goal_choice_never_waits_for_the_models():
    # No ranking yet: the pool comes back unchanged at once, never "wait".
    node = explorer_stub(FakeRanker())
    ranked = FrontierExplorer.rank_by_direction(node, POOL, 0.0, 0.0)
    assert ranked == POOL
    assert logged(node, 'not ready') == 1


def test_a_ready_ranking_made_here_reorders_the_goals():
    node = explorer_stub(FakeRanker())
    node.scene_ranking = DirectionRanking(1, 0.0, 0.0, EAST_OPEN, 'door east',
                                          time.monotonic(), 8)
    ranked = FrontierExplorer.rank_by_direction(node, POOL, 0.0, 0.0)
    assert min(ranked, key=lambda c: c[0])[1] == 1.0
    assert logged(node, 'changes the goal') == 1


def test_a_ranking_made_elsewhere_is_ignored():
    node = explorer_stub(FakeRanker())
    node.scene_ranking = DirectionRanking(1, 5.0, 5.0, EAST_OPEN, 'far away',
                                          time.monotonic(), 8)
    assert FrontierExplorer.rank_by_direction(node, POOL, 0.0, 0.0) == POOL


def test_a_finished_ranking_is_picked_up_at_the_next_goal_choice():
    ranker = FakeRanker(DirectionRanking(1, 0.0, 0.0, EAST_OPEN, 'door east',
                                         time.monotonic(), 3))
    node = explorer_stub(ranker)
    # Scan 1 ended 2 s ago; a newer scan 2 ended just now. The log must time
    # the ranking against its own scan.
    node.scene_scan_ended = {1: time.monotonic() - 2.0, 2: time.monotonic()}
    ranked = FrontierExplorer.rank_by_direction(node, POOL, 0.0, 0.0)
    assert min(ranked, key=lambda c: c[0])[1] == 1.0
    assert logged(node, 'ready 2.0 s after the scan (3 of 8 views described)') == 1


def test_a_failed_ranking_is_reported_and_not_used():
    ranker = FakeRanker(DirectionRanking(1, 0.0, 0.0, None, 'request failed: refused',
                                         time.monotonic(), 0))
    node = explorer_stub(ranker)
    assert FrontierExplorer.rank_by_direction(node, POOL, 0.0, 0.0) == POOL
    assert logged(node, 'Direction ranking failed') == 1
