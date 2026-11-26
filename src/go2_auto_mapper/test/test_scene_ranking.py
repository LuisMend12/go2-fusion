import json
import math
import time

from go2_auto_mapper.scene_ranking import (
    DirectionRanking,
    SceneRanker,
    build_rank_request,
    build_view_request,
    direction_bonus,
    direction_heading,
    parse_direction_scores,
    parse_view_description,
    ranking_usable,
    unknown_toward,
)

FREE, WALL, UNKNOWN = 0, 100, -1


def grid(width, height, fill):
    return [fill] * (width * height)


def put(data, width, x0, x1, y0, y1, value):
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            data[y * width + x] = value


# --- prompts and replies -------------------------------------------------

def test_view_request_sends_one_picture_and_asks_for_json():
    payload = build_view_request('qwen3-vl:8b-instruct', b'\xff\xd8jpeg')
    content = payload['messages'][0]['content']
    assert payload['model'] == 'qwen3-vl:8b-instruct'
    assert [part['type'] for part in content] == ['text', 'image_url']
    assert content[1]['image_url']['url'].startswith('data:image/jpeg;base64,')
    assert payload['response_format'] == {'type': 'json_object'}
    assert payload['temperature'] == 0.0


def test_view_description_is_read_from_json_or_plain_text():
    assert parse_view_description('{"description": "an open hallway"}') == 'an open hallway'
    assert parse_view_description('Sure: {"description": "a wall"} done') == 'a wall'
    assert parse_view_description('a closed door, no JSON') == 'a closed door, no JSON'
    assert parse_view_description('') is None
    assert parse_view_description(None) is None


def test_rank_request_lists_every_direction_with_its_facts():
    facts = [
        {'heading_deg': 22.5, 'description': 'an open doorway', 'unknown_cells': 900,
         'free_m': 3.2},
        {'heading_deg': 67.5, 'description': None, 'unknown_cells': 0, 'free_m': None},
    ]
    payload = build_rank_request('qwen3:30b-a3b-instruct-2507-q4_K_M', facts)
    text = payload['messages'][0]['content']
    assert payload['model'] == 'qwen3:30b-a3b-instruct-2507-q4_K_M'
    assert 'an open doorway' in text and '900' in text and '3.2 m' in text
    assert 'no picture' in text and 'no reading' in text
    assert 'exactly 2' in text
    assert payload['response_format'] == {'type': 'json_object'}


def test_direction_scores_are_clamped_and_must_match_the_count():
    scores, reason = parse_direction_scores('{"scores": [1.5, -1, 0.3], "reason": "door"}', 3)
    assert scores == [1.0, 0.0, 0.3] and reason == 'door'
    assert parse_direction_scores('{"scores": [0.1, 0.2]}', 3)[0] is None
    assert parse_direction_scores('no json here', 3)[0] is None
    assert parse_direction_scores('{"reason": "x"}', 3)[0] is None


# --- map facts -------------------------------------------------------------

def test_unknown_toward_counts_only_its_own_slice():
    # Robot in the middle of a known room; unknown space only to the east.
    w, h = 41, 41
    data = grid(w, h, FREE)
    put(data, w, 31, 40, 0, 40, UNKNOWN)
    east = unknown_toward(data, w, h, 20, 20, 15, 0, 8, 6)
    west = unknown_toward(data, w, h, 20, 20, 15, 4, 8, 6)
    assert east > 0
    assert west == 0


def test_unknown_toward_stops_at_walls():
    w, h = 41, 41
    data = grid(w, h, FREE)
    put(data, w, 31, 40, 0, 40, UNKNOWN)
    put(data, w, 25, 25, 0, 40, WALL)
    assert unknown_toward(data, w, h, 20, 20, 15, 0, 8, 6) == 0


def test_direction_heading_is_the_middle_of_its_slice():
    assert math.isclose(direction_heading(0, 8), math.pi / 8)
    assert math.isclose(direction_heading(4, 8), math.pi + math.pi / 8)


# --- using a ranking ---------------------------------------------------------

def ranking(scores, x=0.0, y=0.0, finished_at=None):
    return DirectionRanking(1, x, y, scores, 'why', time.monotonic()
                            if finished_at is None else finished_at, 8)


def test_bonus_goes_to_goals_in_the_well_scored_direction():
    r = ranking([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    east = direction_bonus(r, math.radians(10), 400.0)     # slice 0
    west = direction_bonus(r, math.radians(190), 400.0)    # slice 4
    assert east == 400.0
    assert west == 0.0


def test_ranking_is_only_used_near_where_and_soon_after_it_was_made():
    now = time.monotonic()
    fresh = ranking([0.5] * 8, finished_at=now)
    assert ranking_usable(fresh, 0.2, 0.1, now, 0.5, 60.0)
    assert not ranking_usable(fresh, 2.0, 0.0, now, 0.5, 60.0)       # moved away
    assert not ranking_usable(ranking([0.5] * 8, finished_at=now - 61.0),
                              0.0, 0.0, now, 0.5, 60.0)               # too old
    assert not ranking_usable(None, 0.0, 0.0, now, 0.5, 60.0)
    assert not ranking_usable(ranking(None, finished_at=now), 0.0, 0.0, now, 0.5, 60.0)


# --- the background worker ---------------------------------------------------

class FakeServer:
    """Answers view requests with a description and rank requests with scores."""

    def __init__(self, scores=None):
        self.calls = []
        self.scores = scores

    def __call__(self, url, payload, timeout, api_key=None):
        self.calls.append((url, payload))
        content = payload['messages'][0]['content']
        if isinstance(content, list):   # a picture to describe
            return json.dumps({'description': f'view {len(self.calls)}'})
        count = content.count('Direction ')
        scores = self.scores or [0.5] * count
        return json.dumps({'scores': scores, 'reason': 'test'})


def wait_for(ranker, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        result = ranker.take_result()
        if result is not None:
            return result
        time.sleep(0.01)
    return None


def test_worker_describes_views_then_ranks_all_directions():
    server = FakeServer(scores=[0.9, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1])
    ranker = SceneRanker('http://vlm', 'vlm-model', 'http://llm', 'llm-model', 5.0,
                         encode=lambda frame: b'jpeg', bins=8, post=server)
    ranker.start_scan(7)
    for b in (0, 1, 2):
        ranker.add_view(7, b, object())
    facts = [{'heading_deg': 22.5 + 45 * b, 'unknown_cells': 10 * b, 'free_m': 2.0}
             for b in range(8)]
    ranker.finish_scan(7, 1.0, 2.0, facts)
    result = wait_for(ranker)
    assert result is not None
    assert result.scan_id == 7 and (result.x, result.y) == (1.0, 2.0)
    assert result.scores[0] == 0.9
    assert result.described == 3
    urls = [url for url, _ in server.calls]
    assert urls == ['http://vlm'] * 3 + ['http://llm']
    rank_text = server.calls[-1][1]['messages'][0]['content']
    assert 'view 1' in rank_text and 'no picture' in rank_text


def test_worker_drops_views_from_an_older_scan():
    server = FakeServer()
    ranker = SceneRanker('http://vlm', 'vlm-model', 'http://llm', 'llm-model', 5.0,
                         encode=lambda frame: b'jpeg', bins=8, post=server)
    ranker.start_scan(1)
    ranker.start_scan(2)
    ranker.add_view(1, 0, object())     # late frame from scan 1: ignored
    ranker.finish_scan(2, 0.0, 0.0, [{'heading_deg': 0.0, 'unknown_cells': 0,
                                      'free_m': None}] * 8)
    result = wait_for(ranker)
    assert result is not None and result.scan_id == 2 and result.described == 0
    assert [url for url, _ in server.calls] == ['http://llm']


def test_worker_reports_a_failed_request_without_dying():
    def broken(url, payload, timeout, api_key=None):
        raise OSError('connection refused')
    ranker = SceneRanker('http://vlm', 'vlm-model', 'http://llm', 'llm-model', 5.0,
                         encode=lambda frame: b'jpeg', bins=8, post=broken)
    ranker.start_scan(3)
    ranker.add_view(3, 0, object())
    ranker.finish_scan(3, 0.0, 0.0, [{'heading_deg': 0.0, 'unknown_cells': 0,
                                      'free_m': None}] * 8)
    result = wait_for(ranker)
    assert result is not None and result.scores is None
    assert 'connection refused' in result.reason
