import asyncio
import time
from types import SimpleNamespace

from go2_robot_sdk.infrastructure.webrtc.connection_health import (
    DATA_STALL_TIMEOUT_SEC,
    data_stalled,
)


def test_no_message_yet_is_not_a_stall():
    # Still connecting: nothing has arrived, but nothing has stopped either.
    assert not data_stalled(None, 1000.0)


def test_recent_message_is_not_a_stall():
    assert not data_stalled(100.0, 100.0 + DATA_STALL_TIMEOUT_SEC - 0.1)


def test_silence_past_the_timeout_is_a_stall():
    assert data_stalled(100.0, 100.0 + DATA_STALL_TIMEOUT_SEC + 0.1)


def _adapter_with(last_message_mono):
    """A WebRTCAdapter holding one fake connection for robot '0'. Needs the
    driver's dependencies (aiortc), so run inside the Docker container."""
    from go2_robot_sdk.infrastructure.webrtc.webrtc_adapter import WebRTCAdapter

    adapter = WebRTCAdapter.__new__(WebRTCAdapter)
    adapter.connections = {'0': SimpleNamespace(last_message_mono=last_message_mono)}
    adapter.disconnected_events = {'0': asyncio.Event()}
    return adapter


def test_adapter_reports_a_stalled_channel_as_lost():
    adapter = _adapter_with(time.monotonic() - DATA_STALL_TIMEOUT_SEC - 1.0)
    assert not adapter.is_connected('0')
    # Latched, so the retry logic sees it even if a message arrives late.
    adapter.connections['0'].last_message_mono = time.monotonic()
    assert not adapter.is_connected('0')


def test_adapter_keeps_a_live_or_starting_channel():
    assert _adapter_with(time.monotonic()).is_connected('0')
    assert _adapter_with(None).is_connected('0')
