"""Tests for the YOLO server client (no ROS needed)."""

import base64

import pytest

from object_detection.remote_yolo import (
    build_request,
    Detection,
    parse_detections,
    send_scale,
    ServerGate,
)


def test_wide_pictures_are_shrunk_to_640_and_small_ones_sent_as_is():
    assert send_scale(1280) == 0.5
    assert send_scale(640) == 1.0
    assert send_scale(320) == 1.0


def test_request_carries_the_jpeg_threshold_and_classes():
    body = build_request(b'\xff\xd8jpeg', 0.5, ['person', 'chair'])
    assert base64.b64decode(body['image']) == b'\xff\xd8jpeg'
    assert body['conf'] == 0.5
    assert body['classes'] == ['person', 'chair']


def test_boxes_are_scaled_back_to_the_full_picture():
    reply = {'detections': [{'label': 'chair', 'confidence': 0.8, 'box': [10, 20, 30, 60]}]}
    assert parse_detections(reply, scale=0.5) == [Detection('chair', 0.8, 20, 40, 60, 120)]


def test_no_detections_is_an_empty_list():
    assert parse_detections({'detections': [], 'seconds': 0.01}) == []


@pytest.mark.parametrize('reply', [
    None,
    {'error': 'GPU out of memory'},
    {'detections': [{'label': 'chair', 'confidence': 0.8}]},
    {'detections': [{'label': 'chair', 'confidence': 'high', 'box': [0, 0, 1, 1]}]},
    {'detections': [{'label': 'chair', 'confidence': 0.8, 'box': [0, 5, 1, 5]}]},
    {'detections': [{'label': 'chair', 'confidence': float('nan'), 'box': [0, 0, 1, 1]}]},
])
def test_a_reply_the_server_would_not_send_is_rejected(reply):
    with pytest.raises(ValueError):
        parse_detections(reply)


def test_after_a_failure_the_server_is_skipped_for_a_while_then_tried_again():
    gate = ServerGate(retry_sec=30.0)
    assert gate.use_server(0.0)
    assert gate.failed(0.0)            # first failure: worth a warning
    assert not gate.use_server(10.0)
    assert gate.use_server(30.0)
    assert not gate.failed(30.0)       # still down: no second warning
    assert gate.succeeded()            # back: worth a note
    assert not gate.succeeded()
    assert gate.use_server(31.0)
