"""
Describe the camera views during a scan, then let a language model rank directions.

Two models, two jobs (vlm_mode 'describe'):

- A vision-language model (VLM) looks at the camera picture for each slice of
  the 360 degree scan and describes it in one sentence, while the robot turns.
- A text model (LLM) reads those sentences plus what the map and lidar say for
  each direction and scores every direction 0..1 for how much new space walking
  that way would reveal.

Everything runs on a background thread. The explorer never waits for it: at a
goal choice it uses the latest ranking if one is ready and was made near where
the robot stands, and the map score alone otherwise. Lidar, SLAM and Nav2 still
decide where the robot can walk; a ranking only reorders goals the map offered.

Nothing here needs ROS, so it can be tested with hand-made data.
"""

import base64
import json
import math
import queue
import re
import threading
import time
from collections import namedtuple

from go2_auto_mapper.frontier_scoring import OCCUPIED_THRESHOLD, UNKNOWN
from go2_auto_mapper.vlm_ranking import heading_bin, post_chat

VIEW_PROMPT = (
    'You are the camera of a robot dog mapping an unfamiliar indoor building. In one '
    'short sentence, say what this view shows for exploring: an open doorway, a '
    'hallway or an open room, or a wall, closed door, dead end or furniture. Chair '
    'legs and gaps under desks are not paths. Do not guess what you cannot see. '
    'Reply with JSON only: {"description": "one short sentence"}'
)

RANK_PROMPT = (
    'A robot dog, 0.81 m long and 0.40 m wide, is mapping an indoor building. It just '
    'turned a full circle. For each direction below (map heading in degrees) you get '
    'what its camera saw and what its map says: how many unknown map cells lie within '
    '4 m that way, and how far the lidar sees before something blocks it. Score each '
    'direction from 0.0 to 1.0 for how much new space walking that way would reveal. '
    'Open doorways, hallways and open rooms score high; walls, closed doors, dead ends '
    'and furniture score low. Where there is no picture, judge from the map numbers '
    'alone. Reply with JSON only, with exactly {n} scores in the order given: '
    '{{"scores": [one number per direction], "reason": "one short sentence"}}\n'
)

# One finished ranking: which scan it belongs to, where the robot stood, one
# score per direction (None if the request failed), the model's reason or the
# error, time.monotonic() when it finished, and how many views were described.
DirectionRanking = namedtuple(
    'DirectionRanking', 'scan_id x y scores reason finished_at described'
)


def direction_heading(index, bins):
    """Return the map heading (radians) in the middle of slice `index` of `bins`."""
    return (index + 0.5) * 2.0 * math.pi / bins


def build_view_request(model, jpeg):
    """Build the chat-completions payload asking the VLM to describe one picture."""
    url = 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode('ascii')
    return {
        'model': model,
        'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': VIEW_PROMPT},
            {'type': 'image_url', 'image_url': {'url': url}},
        ]}],
        'temperature': 0.0,
        'max_tokens': 60,
        'response_format': {'type': 'json_object'},
    }


def parse_view_description(text):
    """
    Return the description from the VLM's reply.

    The reply itself if it had no JSON, or None if it was empty.
    """
    if not text:
        return None
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match is not None:
        try:
            description = json.loads(match.group(0)).get('description')
            if description:
                return str(description).strip()
        except (ValueError, AttributeError):
            pass
    return text.strip() or None


def build_rank_request(model, facts):
    """
    Build the chat-completions payload asking the LLM to score every direction.

    facts: one dict per direction with heading_deg, description (or None),
    unknown_cells and free_m (or None).
    """
    lines = []
    for i, fact in enumerate(facts, start=1):
        seen = fact.get('description') or 'no picture'
        free = fact.get('free_m')
        lidar = 'no reading' if free is None else f'{free:.1f} m'
        lines.append(
            f'Direction {i} (heading {fact["heading_deg"]:.0f} deg): camera: {seen}; '
            f'map: {fact["unknown_cells"]} unknown cells; lidar: {lidar}.'
        )
    return {
        'model': model,
        'messages': [{'role': 'user',
                      'content': RANK_PROMPT.format(n=len(facts)) + '\n'.join(lines)}],
        'temperature': 0.0,
        'max_tokens': 200,
        'response_format': {'type': 'json_object'},
    }


def parse_direction_scores(text, count):
    """
    Return (scores, reason) from the LLM's reply, or (None, why) if unusable.

    Scores are clamped to 0..1, and there must be exactly one per direction.
    """
    match = re.search(r'\{.*\}', text or '', re.DOTALL)
    if match is None:
        return None, 'reply had no JSON'
    try:
        data = json.loads(match.group(0))
        scores = [min(1.0, max(0.0, float(s))) for s in data['scores']]
    except (ValueError, KeyError, TypeError):
        return None, 'reply JSON had no usable "scores" list'
    if len(scores) != count:
        return None, f'expected {count} scores, got {len(scores)}'
    return scores, str(data.get('reason', ''))


def unknown_toward(data, width, height, gx, gy, range_cells, index, bins, rays):
    """
    Count the unknown cells the lidar could see from cell (gx, gy) in one slice.

    The slice is `index` of `bins`: `rays` rays spread across it, each stopping at a
    wall or the grid edge, each cell counted once.
    """
    seen = set()
    width_rad = 2.0 * math.pi / bins
    for r in range(rays):
        angle = (index + (r + 0.5) / rays) * width_rad
        dx, dy = math.cos(angle), math.sin(angle)
        for step in range(1, range_cells + 1):
            x = int(math.floor(gx + 0.5 + dx * step))
            y = int(math.floor(gy + 0.5 + dy * step))
            if not (0 <= x < width and 0 <= y < height):
                break
            value = data[y * width + x]
            if value >= OCCUPIED_THRESHOLD:
                break
            if value == UNKNOWN:
                seen.add((x, y))
    return len(seen)


def ranking_usable(ranking, x, y, now, max_offset_m, max_age):
    """
    Check that a ranking can be used here and now.

    True if `ranking` has scores, was made within `max_offset_m` of (x, y)
    and finished at most `max_age` seconds ago.
    """
    if ranking is None or ranking.scores is None:
        return False
    if now - ranking.finished_at > max_age:
        return False
    return math.hypot(ranking.x - x, ranking.y - y) <= max_offset_m


def direction_bonus(ranking, goal_bearing, weight):
    """
    Return the cells of information gain a goal earns for its direction.

    That is `weight` times the score (0..1) of the direction the goal lies in.
    """
    index = heading_bin(goal_bearing, len(ranking.scores))
    return weight * ranking.scores[index]


class SceneRanker:
    """
    Describe views and rank directions on one background thread.

    The explorer calls start_scan() when a scan starts, add_view() for each
    new slice the camera covers, and finish_scan() when the turn ends. Jobs run
    in order on one thread, so the ranking request goes out after the scan's
    pictures are described. take_result() hands over a finished ranking once.
    """

    def __init__(self, vlm_url, vlm_model, llm_url, llm_model, timeout, encode,
                 bins=8, api_key=None, post=post_chat):
        self.vlm_url, self.vlm_model = vlm_url, vlm_model
        self.llm_url, self.llm_model = llm_url, llm_model
        self.timeout = timeout
        self.encode = encode
        self.bins = bins
        self.api_key = api_key
        self.post = post
        self.lock = threading.Lock()
        self.jobs = queue.Queue()
        self.scan_id = None
        self.descriptions = {}
        self.result = None
        self.thread = threading.Thread(target=self._work, daemon=True)
        self.thread.start()

    def start_scan(self, scan_id):
        with self.lock:
            self.scan_id = scan_id
            self.descriptions = {}

    def add_view(self, scan_id, index, frame):
        self.jobs.put(('describe', scan_id, index, frame))

    def finish_scan(self, scan_id, x, y, facts):
        self.jobs.put(('rank', scan_id, (x, y), facts))

    def take_result(self):
        """Return the finished DirectionRanking once; None while waiting or if taken."""
        with self.lock:
            result, self.result = self.result, None
        return result

    def _current(self, scan_id):
        with self.lock:
            return scan_id == self.scan_id

    def _work(self):
        while True:
            job = self.jobs.get()
            try:
                if job[0] == 'describe':
                    self._describe(*job[1:])
                else:
                    self._rank(*job[1:])
            except Exception as e:  # never let the thread die silently
                if job[0] == 'rank':
                    self._store(job[1], job[2], None, f'unexpected error: {e!r}', 0)

    def _describe(self, scan_id, index, frame):
        if not self._current(scan_id):
            return   # a late frame from an older scan
        try:
            text = self.post(self.vlm_url, build_view_request(self.vlm_model, self.encode(frame)),
                             self.timeout, self.api_key)
        except (OSError, ValueError, KeyError, IndexError):
            return   # this direction goes to the LLM as "no picture"
        description = parse_view_description(text)
        with self.lock:
            if scan_id == self.scan_id and description:
                self.descriptions[index] = description

    def _rank(self, scan_id, pose, facts):
        if not self._current(scan_id):
            return
        with self.lock:
            descriptions = dict(self.descriptions)
        filled = [dict(fact, description=descriptions.get(i)) for i, fact in enumerate(facts)]
        try:
            text = self.post(self.llm_url, build_rank_request(self.llm_model, filled),
                             self.timeout, self.api_key)
            scores, reason = parse_direction_scores(text, len(facts))
        except (OSError, ValueError, KeyError, IndexError) as e:
            scores, reason = None, f'request failed: {e}'
        self._store(scan_id, pose, scores, reason, len(descriptions))

    def _store(self, scan_id, pose, scores, reason, described):
        with self.lock:
            self.result = DirectionRanking(scan_id, pose[0], pose[1], scores, reason,
                                           time.monotonic(), described)
