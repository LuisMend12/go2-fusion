"""Asking a vision-language model (VLM) which frontier looks most worth
exploring, from the camera's view toward each one.

The model runs on a GPU server behind an OpenAI-compatible chat API (vLLM
and Ollama both serve one), usually reached through an SSH tunnel. Nothing
here needs ROS, so it can be tested with hand-made data.

The VLM only re-ranks goals the explorer already found free and clear of
walls: lidar, SLAM and Nav2 still decide where the robot can walk.
"""

import base64
import json
import math
import re
import threading
import time
import urllib.error
import urllib.request
from collections import namedtuple

from go2_auto_mapper.obstacle_sensing import angle_difference

# The score a candidate gets when the VLM can't judge it (no camera view
# toward it): neither a bonus nor a penalty.
NEUTRAL_SCORE = 0.5

PROMPT = (
    'You are helping a robot dog map an unfamiliar indoor building. Each of '
    'the {n} images below is its camera view toward a different unexplored '
    'area. For each one, rate from 0.0 to 1.0 how likely walking that way '
    'reveals a lot of new space: an open doorway, a hallway or an open room '
    'score high; a wall, a closed door, a dead end, or clutter score low. '
    'Reply with JSON only, in this form: '
    '{{"scores": [one number per image, in order], "reason": "one short sentence"}}'
)

DESCRIBE_PROMPT = (
    'You are the camera of a small robot dog. Describe what you see in 3 short '
    'sentences: the room, objects and people, and whether there is open space '
    'or a doorway to walk through.'
)

# One finished request: the goals asked about as (x, y), the score for
# each (None if the request failed), the model's one-line reason or the
# error, and time.monotonic() when it finished.
Ranking = namedtuple('Ranking', 'goals scores reason finished_at')


def heading_bin(yaw, bins):
    """Which of `bins` equal slices of a full turn the heading falls in."""
    turn = (yaw % (2.0 * math.pi)) / (2.0 * math.pi)
    return int(turn * bins) % bins


class ViewMemory:
    """The latest camera frame per heading, with where the robot stood.

    The robot turns a full circle at the start and after every goal, so
    this fills with a view in every direction from where it now stands.
    Frames are kept as-is; they are only encoded when a request is sent.
    """

    def __init__(self, bins=8):
        self.bins = bins
        self.views = {}

    def remember(self, x, y, yaw, frame, now):
        self.views[heading_bin(yaw, self.bins)] = (x, y, yaw, frame, now)

    def view_toward(self, x, y, bearing, now, max_offset_m, max_angle, max_age):
        """The frame best facing `bearing` from near (x, y), or None.

        A view only counts if it was taken within `max_offset_m` of (x, y),
        at most `max_age` seconds ago, and within `max_angle` radians of
        the bearing; otherwise it shows a different place or direction.
        """
        best = None
        for vx, vy, yaw, frame, taken in self.views.values():
            if now - taken > max_age:
                continue
            if math.hypot(vx - x, vy - y) > max_offset_m:
                continue
            off = angle_difference(yaw, bearing)
            if off <= max_angle and (best is None or off < best[0]):
                best = (off, frame)
        return None if best is None else best[1]


def build_request(model, jpegs):
    """Chat-completions payload asking the model to score each image."""
    content = [{'type': 'text', 'text': PROMPT.format(n=len(jpegs))}]
    for i, jpeg in enumerate(jpegs, start=1):
        content.append({'type': 'text', 'text': f'Image {i}:'})
        content.append({
            'type': 'image_url',
            'image_url': {
                'url': 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode('ascii')
            },
        })
    return {
        'model': model,
        'messages': [{'role': 'user', 'content': content}],
        'temperature': 0.0,
        'max_tokens': 200,
    }


def build_describe_request(model, jpeg):
    """Chat-completions payload asking the model to describe one image."""
    url = 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode('ascii')
    return {
        'model': model,
        'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': DESCRIBE_PROMPT},
            {'type': 'image_url', 'image_url': {'url': url}},
        ]}],
        'temperature': 0.0,
        'max_tokens': 160,
    }


def parse_reply(text, count):
    """(scores, reason) from the model's reply, or (None, why) if unusable.

    Models often wrap JSON in prose or a code fence, so the first {...}
    block is read. Scores are clamped to 0..1, and there must be exactly
    one per image.
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


def merge_scores(has_view, scores):
    """One score per candidate: the model's, in order, for those with a
    view, and NEUTRAL_SCORE for those without (the model never saw them)."""
    model_scores = iter(scores)
    return [next(model_scores) if seen else NEUTRAL_SCORE for seen in has_view]


def vlm_bonus(score, weight):
    """Cells of information gain a VLM score is worth: +weight/2 for a
    sure yes, -weight/2 for a sure no, 0 for a shrug."""
    return weight * (score - NEUTRAL_SCORE)


def match_score(ranking, x, y, radius):
    """The ranking's score for the goal within `radius` of (x, y), or None.

    Goals move a little each time SLAM updates the map, so they are
    matched by distance rather than exactly.
    """
    if ranking is None or ranking.scores is None:
        return None
    best = None
    for (gx, gy), score in zip(ranking.goals, ranking.scores):
        d = math.hypot(gx - x, gy - y)
        if d <= radius and (best is None or d < best[0]):
            best = (d, score)
    return None if best is None else best[1]


def post_chat(url, payload, timeout, api_key=None):
    """Send a chat-completions request; the reply's text."""
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode('utf-8'), headers=headers
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode('utf-8'))
    return body['choices'][0]['message']['content']


class VlmClient:
    """Sends one request at a time on a background thread, so the
    explorer's timer (which also watches for obstacles) never waits on the
    network. The explorer polls take_result() on its next loop.
    """

    def __init__(self, url, model, timeout, encode, api_key=None, post=post_chat):
        self.url = url
        self.model = model
        self.timeout = timeout
        self.encode = encode
        self.api_key = api_key
        self.post = post
        self.lock = threading.Lock()
        self.thread = None
        self.result = None

    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def submit(self, goals, frames):
        """Ask about `goals` [(x, y)], with a camera frame (or None) each."""
        if self.busy():
            return False
        self.thread = threading.Thread(
            target=self._run, args=(list(goals), list(frames)), daemon=True
        )
        self.thread.start()
        return True

    def take_result(self):
        """The finished Ranking, once; None while waiting or if taken."""
        with self.lock:
            result, self.result = self.result, None
        return result

    def _run(self, goals, frames):
        has_view = [frame is not None for frame in frames]
        try:
            jpegs = [self.encode(frame) for frame in frames if frame is not None]
            text = self.post(
                self.url, build_request(self.model, jpegs), self.timeout, self.api_key
            )
            scores, reason = parse_reply(text, len(jpegs))
            if scores is not None:
                scores = merge_scores(has_view, scores)
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError) as e:
            scores, reason = None, f'request failed: {e}'
        except Exception as e:  # never let the thread die silently
            scores, reason = None, f'unexpected error: {e!r}'
        with self.lock:
            self.result = Ranking(goals, scores, reason, time.monotonic())
