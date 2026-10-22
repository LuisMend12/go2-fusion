---
title: Maps and navigation
parent: oak
---

# Maps and navigation

How Oak builds a map of a room and walks to a goal on it.

Part of: [Oak](../../README.md)

## Pages

- [SLAM](slam.md) - slam_toolbox builds a 2D map of the room from `/scan` and odometry.
- [Nav2](nav2.md) - Nav2 plans a path to a goal on the map and publishes on `/cmd_vel` (twist_mux priority 5).
- [Auto mapper](auto-mapper.md) - Autonomous frontier exploration: finds unexplored edges of the SLAM map and sends Nav2 goals there. It moves the robot on its own.
- [Map viewers](map-viewers.md) - Two learning viewers of the live SLAM map: an SFML C++ window and a Julia one; click a cell to send a Nav2 goal.

<!-- TODO: content -->
