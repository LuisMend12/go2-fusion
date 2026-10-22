---
title: RViz panels
parent: driving
code: [src/go2_rviz_plugins/**]
---

# RViz panels

These are three control panels that live inside RViz (ROS's 3D viewer), so you can click to send Oak somewhere, run the auto mapper, or drive with the keyboard, all from one window.

Part of: [Driving](driving.md)

## How it works

The package `go2_rviz_plugins` adds three panels to RViz as plugins (add-ons RViz loads), not as separate apps.
The default RViz layout, `single_robot_conf.rviz`, already includes all three, so they appear when `robot.launch.py` opens RViz.

- **MapViewer** shows the live SLAM map (from `/map`). Click anywhere to send Oak there as a Nav2 goal (through the `/navigate_to_pose` action); **Cancel Goal** stops it. It draws the map with Qt instead of RViz's own Map display, because that display crashes under WSL's software graphics. It is the same idea as the standalone [map viewer](map-viewers.md), just docked inside RViz.
- **AutoMapper** has **Start** and **Stop** buttons for the [auto mapper](auto-mapper.md) explorer, with its log shown live. **Scan** asks the explorer to turn Oak 360 degrees so SLAM can find itself (the robot moves). **Reset maps** (asks to confirm) restarts the 2D map and clears the 3D point cloud, starting both over from where Oak stands.
- **KeyboardTeleop** lets you drive with the same keys as [keyboard teleop](keyboard-teleop.md) (W/S, A/D, Q/E, Z/X, Space or Esc to stop). Click the panel first so it has focus. It publishes on `/cmd_vel_keyboard`, the same priority-9 lane.

Unlike the terminal version, the panel sees real key releases, so letting go stops at once.
Key changes are sent immediately, and while keys are held it repeats the command 20 times a second to keep its [twist_mux](twist-mux.md) lane alive.
Clicking elsewhere (losing focus) releases every key and sends a stop.

## Connects to

- [twist_mux](twist-mux.md): KeyboardTeleop publishes `/cmd_vel_keyboard` (priority 9).
- [Nav2](nav2.md): MapViewer sends goals to `/navigate_to_pose`.
- [Auto mapper](auto-mapper.md): AutoMapper starts the `explorer` and calls its `/frontier_explorer/scan` service.
- [SLAM](slam.md) and [Lidar](lidar.md): Reset maps restarts `slam_toolbox` and calls `/lidar_to_pointcloud/reset`.
- [Map viewers](map-viewers.md): the standalone versions of MapViewer.

## How it breaks

- **AutoMapper moves the robot on its own.** Only press Start or Scan when you are in the room watching Oak.
- **Idle zeros (fixed):** the KeyboardTeleop panel used to send zeros about 4 times a second, which blocked Nav2, the agent and object navigation. Found on the robot 2026-10-11 and fixed.
- **Laggy keys (fixed):** a key press used to wait up to 100 ms for the next timer tick. Fixed 2026-10-19 by sending changes immediately.
- **Reset maps pauses navigation** for a few seconds while SLAM restarts.
- **MapViewer click-to-walk is not retested** on the current code; it is an open item in the [test log](test-log.md).
- **No window at all:** RViz needs a display. On Windows, see [WSL and Windows](wsl.md).

## Who's on it and what's next

Luis built these panels, added Scan and Reset maps (2026-10-16), and made KeyboardTeleop respond instantly (2026-10-19). Next: full exploration tests on Oak with the auto mapper.

## The code

https://github.com/maxhawksby/go2-fusion/tree/master/src/go2_rviz_plugins

This is C++, so after a change rebuild it in a running container (see [Docker](docker.md)), then restart RViz:

```shell
docker compose exec unitree_ros bash -ic 'cbs go2_rviz_plugins'
```

To add a panel by hand: RViz **Panels > Add New Panel > go2_rviz_plugins**, then **File > Save Config**.

<!-- sources: src/go2_rviz_plugins/README.md; src/go2_rviz_plugins/src/*.cpp (/map, /navigate_to_pose, /frontier_explorer/scan, /lidar_to_pointcloud/reset, kPublishRateHz 20); src/go2_robot_sdk/config/single_robot_conf.rviz Panels; docs/FUSION.md rows 7, 9, 16; docs/TEST_LOG.md 2026-10-11 and open issue 1; git log e1bdf14, 264939b, a51627d; team update 2026-10-18 (Luis) -->
