"""HTTP server around YOLO on a GPU, so the robot laptop needs no GPU.

POST /detect  {"image": base64 JPEG, "conf": minimum confidence (default 0.25),
               "classes": [names] (YOLOE weights only; [] keeps the model's own)}
           -> {"detections": [{"label", "confidence", "box": [x1, y1, x2, y2] pixels}],
               "seconds": s}
GET  /health  -> {"model": weights file, "device": "cuda:N", "gpu_gb": memory in use}

The object_detection node (inference_url, or YOLO_URL) sends one picture per
request and does everything else (positions, memory, people) itself.
"""

import base64
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
import torch
from ultralytics import YOLO

MODEL_PATH = os.environ.get('YOLO_MODEL', 'yolov8n.pt')
PORT = int(os.environ.get('YOLO_PORT', '8200'))
DEVICE = os.environ.get('YOLO_DEVICE', 'cuda:0' if torch.cuda.is_available() else 'cpu')
# Bigger requests are refused: a 640-wide JPEG is well under 1 MB.
MAX_BODY_BYTES = 8 * 1024 * 1024


class Service:

    def __init__(self):
        self.model = YOLO(MODEL_PATH)
        self.classes = []
        # One picture at a time on the GPU; set_classes changes the model.
        self.lock = threading.Lock()
        # Warm up, so the first real request is not slow.
        self.model(np.zeros((360, 640, 3), np.uint8), device=DEVICE, verbose=False)

    def detect(self, request):
        data = np.frombuffer(base64.b64decode(request['image'], validate=True), np.uint8)
        frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError('image is not a JPEG or PNG')
        conf = float(request.get('conf', 0.25))
        classes = [str(c) for c in request.get('classes', [])]
        with self.lock:
            if classes != self.classes:
                if classes and not hasattr(self.model, 'set_classes'):
                    raise ValueError(f'{MODEL_PATH} has fixed classes; classes needs YOLOE weights')
                if classes:
                    self.model.set_classes(classes)
                self.classes = classes
            result = self.model(frame, conf=conf, device=DEVICE, verbose=False)[0]
        names = result.names
        return {'detections': [
            {'label': names[int(c)], 'confidence': round(float(p), 3),
             'box': [round(float(v), 1) for v in xyxy]}
            for c, p, xyxy in zip(result.boxes.cls, result.boxes.conf, result.boxes.xyxy)
        ]}


def make_handler(service):

    class Handler(BaseHTTPRequestHandler):

        def reply(self, code, data):
            payload = json.dumps(data).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path != '/health':
                self.reply(404, {'error': 'unknown path'})
                return
            gpu_gb = torch.cuda.memory_allocated() / 1e9 if DEVICE.startswith('cuda') else 0.0
            self.reply(200, {'model': MODEL_PATH, 'device': DEVICE, 'gpu_gb': round(gpu_gb, 2)})

        def do_POST(self):
            if self.path != '/detect':
                self.reply(404, {'error': 'unknown path'})
                return
            started = time.monotonic()
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= MAX_BODY_BYTES:
                    raise ValueError(f'body must be 1 to {MAX_BODY_BYTES} bytes')
                request = json.loads(self.rfile.read(length))
                self.reply(200, {**service.detect(request),
                                 'seconds': round(time.monotonic() - started, 4)})
            except (KeyError, TypeError, ValueError) as e:
                self.reply(400, {'error': str(e)})
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                self.reply(503, {'error': 'GPU out of memory'})

        def log_message(self, *args):
            pass

    return Handler


if __name__ == '__main__':
    service = Service()
    print(f'YOLO {MODEL_PATH} ready on {DEVICE}, port {PORT}', flush=True)
    # Localhost by default: this has no password, so reach it over an SSH tunnel.
    host = os.environ.get('YOLO_HOST', '127.0.0.1')
    ThreadingHTTPServer((host, PORT), make_handler(service)).serve_forever()
