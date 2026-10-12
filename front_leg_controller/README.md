# front_leg_controller

Two separate nodes:

- `front_leg_controller` — a placeholder. It logs simulated leg motion but
  never sends a real command. Currently inert; see
  [go2_auto_mapper/README.md](../go2_auto_mapper/README.md#known-limitations).
- `sit_controller` — **not** inert. It sends a real Sit command (API 1009)
  to the physical robot over `/webrtc_req`. See below.

## Sport API commands

The Go2's built-in moves/gestures (what Unitree's own app exposes as
quick-action buttons) are sent as a `go2_interfaces/msg/WebRtcReq` message
on `/webrtc_req`, with `api_id` set to one of the values below and
`topic: "rt/api/sport/request"`. Full list: `ROBOT_CMD` in
[go2_robot_sdk/go2_robot_sdk/domain/constants/robot_commands.py](../go2_robot_sdk/go2_robot_sdk/domain/constants/robot_commands.py).

**Movement/posture**
| Command | API ID |
|---|---|
| Damp | 1001 |
| BalanceStand | 1002 |
| StopMove | 1003 |
| StandUp | 1004 |
| StandDown | 1005 |
| RecoveryStand | 1006 |
| Euler | 1007 |
| Move | 1008 |
| Sit | 1009 |
| RiseSit | 1010 |
| SwitchGait | 1011 |
| Trigger | 1012 |
| BodyHeight | 1013 |
| FootRaiseHeight | 1014 |
| SpeedLevel | 1015 |
| TrajectoryFollow | 1018 |
| ContinuousGait | 1019 |
| GetBodyHeight | 1024 |
| GetFootRaiseHeight | 1025 |
| GetSpeedLevel | 1026 |
| SwitchJoystick | 1027 |
| Pose | 1028 |
| GetState | 1034 |
| EconomicGait | 1035 |
| StandOut | 1039 |
| FreeWalk | 1045 |
| Standup | 1050 |
| CrossWalk | 1051 |

**Fun / show moves**
| Command | API ID |
|---|---|
| Hello | 1016 |
| Stretch | 1017 |
| Content | 1020 |
| Wallow | 1021 |
| Dance1 | 1022 |
| Dance2 | 1023 |
| Scrape | 1029 |
| FrontFlip | 1030 |
| FrontJump | 1031 |
| FrontPounce | 1032 |
| WiggleHips | 1033 |
| FingerHeart ("show love") | 1036 |
| Handstand | 1301 |
| CrossStep | 1302 |
| OnesidedStep | 1303 |
| Bound | 1304 |
| MoonWalk | 1305 |

**Caution:** these move the physical robot. Only trigger them when you're
physically present and watching the robot, in a cleared area.

## Sending one

`sit_controller.py` is a complete, working example of this pattern — it
waits for an actual subscriber on `/webrtc_req` (so the command isn't
silently dropped if the driver isn't up yet), builds the message, and
publishes once:

```shell
docker exec -it docker-unitree_ros-1 bash -ic 'ros2 run front_leg_controller sit_controller'
```

To trigger a different command ad hoc without writing a node, publish
directly from the command line — e.g. for `FingerHeart` (1036):

```shell
ros2 topic pub --once /webrtc_req go2_interfaces/msg/WebRtcReq \
  "{id: 0, topic: 'rt/api/sport/request', api_id: 1036, parameter: '{}', priority: 0}"
```

Most of these commands take an empty JSON object (`'{}'`) as `parameter`;
a few (e.g. `Move`, `BodyHeight`, `SpeedLevel`) take real arguments there
instead — check Unitree's own API docs for which ones and what shape.
