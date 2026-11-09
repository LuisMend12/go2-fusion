"""
Ask a YOLO server on a GPU machine for boxes, instead of running YOLO here.

The server is host_tools/yolo_server/server.py, reached over an SSH tunnel like
the auto mapper's VLM. Pictures are shrunk before sending (YOLO looks at 640
pixels anyway) and the boxes are scaled back to the full picture.

No ROS here, so it tests on any machine.
"""

import base64
import json
import math
import urllib.request
from collections import namedtuple

# Width the picture is shrunk to before sending: YOLO's own input size, so
# nothing it would have seen is lost, and each request stays small.
SEND_WIDTH = 640
JPEG_QUALITY = 80
# After the server fails, how long to use the local model before asking it again.
RETRY_SEC = 30.0

Detection = namedtuple('Detection', 'label confidence x1 y1 x2 y2')


def send_scale(width, send_width=SEND_WIDTH):
    """Return the factor a picture this wide is shrunk by (1.0: sent as is)."""
    return min(1.0, send_width / width) if width > 0 else 1.0


def build_request(jpeg, min_confidence, classes=()):
    """Build the /detect body from JPEG bytes."""
    return {
        'image': base64.b64encode(jpeg).decode('ascii'),
        'conf': float(min_confidence),
        'classes': list(classes),
    }


def parse_detections(reply, scale=1.0):
    """
    Turn the server's reply into Detections in full-picture pixels.

    scale is the factor the picture was shrunk by before sending. Raises
    ValueError on a reply that is not what the server sends.
    """
    if not isinstance(reply, dict) or not isinstance(reply.get('detections'), list):
        raise ValueError(f'unexpected reply: {str(reply)[:200]}')
    detections = []
    for entry in reply['detections']:
        try:
            label = str(entry['label'])
            confidence = float(entry['confidence'])
            x1, y1, x2, y2 = (float(v) / scale for v in entry['box'])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f'bad detection {entry!r}: {e}') from e
        if not all(map(math.isfinite, (confidence, x1, y1, x2, y2))) or y2 <= y1 or x2 <= x1:
            raise ValueError(f'bad detection {entry!r}')
        detections.append(Detection(label, confidence, x1, y1, x2, y2))
    return detections


def post_json(url, body, timeout):
    request = urllib.request.Request(
        url, data=json.dumps(body).encode('utf-8'),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


class ServerGate:
    """Whether to ask the server now: not for RETRY_SEC after it failed."""

    def __init__(self, retry_sec=RETRY_SEC):
        self.retry_sec = retry_sec
        self.retry_after = None

    def use_server(self, now):
        return self.retry_after is None or now >= self.retry_after

    def failed(self, now):
        """Note a failure; True if the server had been working until now."""
        was_working = self.retry_after is None
        self.retry_after = now + self.retry_sec
        return was_working

    def succeeded(self):
        """Note a success; True if the server had been failing until now."""
        was_failing = self.retry_after is not None
        self.retry_after = None
        return was_failing
