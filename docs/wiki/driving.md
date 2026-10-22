---
title: Driving
parent: oak
---

# Driving

How people steer Oak by hand, and how every drive command is merged before it reaches the robot.

Part of: [Oak](../../README.md)

## Pages

- [Keyboard teleop](keyboard-teleop.md) - Drives Oak from a terminal keyboard, publishing on `/cmd_vel_keyboard` (twist_mux priority 9) only while a key is held.
- [Gamepad](gamepad.md) - A game controller drives Oak through `joy` and `teleop_twist_joy`, publishing on `/cmd_vel_joy` (priority 10) only while LB is held.
- [RViz panels](rviz-panels.md) - Three RViz plugin panels: a map viewer with click-to-navigate, an auto mapper panel and a keyboard teleop panel.
- [twist_mux](twist-mux.md) - Merges every drive source and forwards the highest-priority active one to the driver; each source has its own input topic.

<!-- TODO: content -->
