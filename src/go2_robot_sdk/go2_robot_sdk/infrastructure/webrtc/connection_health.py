"""Detects a WebRTC data channel that went quiet without closing.

Seen in the lab: the camera video (its own media track) kept arriving while
odometry, IMU, joint states and the lidar cloud (all on the data channel)
stopped. Nothing closed and no connection state changed, so the driver kept
running as if connected and received nothing: no cloud, no /scan, no map.
"""

# The robot sends odometry at about 15 Hz and state topics continuously, so
# this long without a single data-channel message means the channel stalled.
DATA_STALL_TIMEOUT_SEC = 5.0


def data_stalled(last_message_mono, now_mono, timeout=DATA_STALL_TIMEOUT_SEC):
    """True if the data channel has been silent for longer than `timeout`.

    `last_message_mono` is when the last message arrived (monotonic
    seconds), or None before the first one: a connection still being set up
    hasn't stalled, it just hasn't started.
    """

    if last_message_mono is None:
        return False
    return now_mono - last_message_mono > timeout
