---
title: Posture
parent: brains
code: [src/front_leg_controller/**]
---

# Posture

Posture covers Oak's built-in moves, like sit, stand up, stretch and wave hello, which Oak performs by itself when you send it one short command.

Part of: [Brains](brains.md)

## How it works

The Go2 has a library of ready-made moves, the same ones Unitree's phone app shows as quick-action buttons. Each move has a number, called an *API ID*. For example, Stand Up is 1004, Sit is 1009 and Stretch is 1017.

To trigger a move, a program publishes one message on the `/webrtc_req` topic, with the move's API ID and the robot's sport command channel (`rt/api/sport/request`). The [Go2 driver](go2-driver.md) carries it to Oak, and Oak does the rest.

The `front_leg_controller` package holds two programs:

- **`sit_controller`** works for real. It waits until the driver is listening on `/webrtc_req` (so the command is not lost), sends Sit once, and exits. It is the best example of how to send any move.
- **`front_leg_controller`** is a placeholder. It reads `/joint_states` and logs pretend leg motion, but never sends a real command.

## Connects to

- [Go2 driver](go2-driver.md): delivers `/webrtc_req` to the robot.
- [LLM agent](llm-agent.md): Riley's version sends sit, stand up, stand down, recovery stand and stretch the same way.
- [Voice](voice.md): speech out also travels on `/webrtc_req`, on the audio channel instead.
- The Oak Control dashboard (Noah, pull request #14) has quick-action buttons for posture and gestures. See [People](people.md).

## How it breaks

- **These commands move the real robot.** Only send them when you are in the lab, watching Oak, in a cleared area.
- **A message sent before the driver is up is silently dropped.** That is why `sit_controller` waits for a listener first (a fix ported from Luis's work, [Decisions](decisions.md) row 15).
- **The `parameter` field matters.** We standardized on `"{}"` (empty JSON) for Sit. Riley's agent sent `""`; only its Sit was changed ([Decisions](decisions.md) row 11). A few moves, like Move, BodyHeight and SpeedLevel, need real arguments; check Unitree's API docs.
- Sit and stand were **not run yet** in the 2026-10-11 lab session ([Test log](test-log.md)).

## Who's on it and what's next

Nobody is working on posture this week. TODO(Max): whether the placeholder `front_leg_controller` node should be finished or removed.

## The code

Folder: https://github.com/maxhawksby/go2-fusion/tree/master/src/front_leg_controller

The full list of moves and their API IDs is in the package README and in `ROBOT_CMD` in the driver's `robot_commands.py`.

With the robot stack running:

```shell
docker exec -it docker-unitree_ros-1 bash -ic 'ros2 run front_leg_controller sit_controller'
```

Or send any move from the command line, for example FingerHeart (1036):

```shell
ros2 topic pub --once /webrtc_req go2_interfaces/msg/WebRtcReq \
  "{id: 0, topic: 'rt/api/sport/request', api_id: 1036, parameter: '{}', priority: 0}"
```

<!-- sources: src/front_leg_controller/README.md; src/front_leg_controller/front_leg_controller/front_leg_controller.py; src/go2_auto_mapper/README.md "Known limitations"; src/go2_llm_agent/README.md; docs/FUSION.md rows 11, 15; docs/TEST_LOG.md 2026-10-11; origin/feat/desktop-app-prototype (PR #14) -->
