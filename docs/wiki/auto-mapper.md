---
title: Auto mapper
parent: maps-nav
code: [src/go2_auto_mapper/**]
---

# Auto mapper

The auto mapper lets Oak map a room by itself: it keeps finding the edges of what it has already mapped and walks there to see more, until nothing is left to explore. **It moves the robot on its own, so only run it with a person watching Oak in a cleared area.**

Part of: [Maps and navigation](maps-nav.md)

## How it works

**Frontiers.** On the [SLAM](slam.md) map, every 5 cm square is free, wall, or unknown. A frontier is a free square right next to an unknown one: the border between "explored" and "not yet seen". Imagine exploring a dark building with a flashlight: the frontier is every doorway and corner you have glimpsed but not walked through. Go stand at a frontier, look around, and the map grows. Repeat until there are no frontiers left.

**One exploration loop** (node `explorer`, every 2 seconds):

1. **Look around first.** At start and after each goal, Oak turns a full circle using Nav2's Spin behavior, so the lidar sees everything around it and SLAM can place it on the map.
2. **Find frontiers.** It scans `/map` for frontier squares and groups neighbours into regions; regions under 5 squares are treated as noise. Since 2026-10-17 this is one fast numpy pass: about 4.4 ms instead of 0.5 s on a 40 x 40 m map.
3. **Pick a goal.** For each region it picks spots 0.8 m back into known space and at least 0.5 m from walls. It skips directions it was just blocked in, spots closer than 1.5 m, and spots without a clear straight line. Of the rest, it picks the one that would reveal the most: it casts 48 imaginary rays from each spot out to 4 m and counts unknown squares they would uncover, minus a cost per meter of walking.
4. **Go.** It sends the goal to [Nav2](nav2.md) on `/navigate_to_pose`, exactly like clicking "Nav2 Goal" in RViz, so Nav2's obstacle avoidance still applies.
5. **Learn from it.** If a visit did not shrink the frontier (the opening can't be seen into), that frontier is skipped for 2 minutes. Failed goals are also skipped for 2 minutes.
6. **Get unstuck.** If something is within 0.3 m of the nose, it cancels the goal and checks short moves backward, left and right against the live `/scan` and Nav2's local costmap, then slides 0.05 to 0.5 m at 0.1 m/s along the safest one. These moves go out on `/cmd_vel_mapper`, a [twist_mux](twist-mux.md) input at priority 6 (above Nav2, below keyboard and gamepad). If nothing is safe, it stays stopped and logs why.
7. **Head for open space.** After 3 failed goals in a row (or similar signs of being stuck), it drives to the nearest spot with 0.8 m of room on every side, scans, and carries on.
8. **Finish.** With no frontiers left it logs "Exploration complete" and waits, in case a door opens.

**Buttons.** The RViz AutoMapper panel has **Start/Stop**, **Scan** (pause the goal, forget recent failures, turn 360 degrees; the same as calling `/frontier_explorer/scan`) and **Reset maps** (restart SLAM with an empty 2D map and clear the 3D point cloud).

## Connects to

- [SLAM](slam.md) - reads `/map` and the `map` frame.
- [Nav2](nav2.md) - sends goals to `/navigate_to_pose`, uses `/spin` and `/backup`, reads `/local_costmap/costmap`.
- [Lidar](lidar.md) - reads `/scan` and `/point_cloud2` to check it is safe to move.
- [twist_mux](twist-mux.md) - recovery moves on `/cmd_vel_mapper` (priority 6).
- [RViz panels](rviz-panels.md) - the AutoMapper panel starts and stops it.

## How it breaks

From the package README and Luis's commits (Oct 14-19):

- **Stopping for no reason.** Drifted floor points in the 3D cloud were marked as obstacles, and a 0.5 m lidar cut-off hid walls beside the robot. Fixed by giving Nav2 only the filtered 2D scan and lowering the minimum range to 0.1 m.
- **"No usable goal".** Press Scan: it re-looks and retries recently failed spots.
- **Nibbling the nearest edge.** Ranking goals by distance made it creep along the closest frontier; replaced by "most revealed per meter" on 2026-10-16.
- **Two motions at once.** Codex reviews on 2026-10-17 found cases where a late Nav2 reply or a recovery move could override a stop; each maneuver is now tracked until Nav2 confirms it ended, and a latched stop always wins.
- **Waits for fresh data.** After every scan or move it waits up to 20 s for newer `/scan`, `/point_cloud2`, `/map`, costmap and TF. If they don't come, exploration stays stopped until Scan is pressed.
- **The 3D cloud never forgets** moved objects; neither SLAM nor the 3D map is cleared during recovery.
- **Big maps** make each step slower, because the whole map is rescanned every cycle.
- The README's Docker command uses a fixed container name (`docker-unitree_ros-1`) and also shows a non-Docker WSL run; the team rule is to run everything through `docker compose` (AGENTS.md).

## Who's on it and what's next

**Luis** owns the auto mapper. In the week of 2026-10-18 he made exploration reliable (fixes above, Scan and Reset maps buttons, faster frontiers, Nav2 and SLAM tuning) and merged it to master. Next: full exploration tests on Oak.

## The code

https://github.com/maxhawksby/go2-fusion/tree/master/src/go2_auto_mapper (`explorer.py` runs the loop; `frontier_scoring.py`, `recovery.py`, `obstacle_sensing.py` and `open_space.py` hold the logic that has unit tests).

With the robot stack running (SLAM and Nav2 on) and a person watching Oak:

```shell
cd docker
docker compose exec unitree_ros bash -ic 'ros2 run go2_auto_mapper explorer'
```

Ctrl+C stops it and cancels the Nav2 goal. Emergency stop from another terminal:

```shell
docker compose exec unitree_ros bash -ic 'ros2 service call /navigate_to_pose/_action/cancel_goal action_msgs/srv/CancelGoal "{}"'
docker compose exec unitree_ros bash -ic 'ros2 topic pub /cmd_vel_joy geometry_msgs/msg/Twist "{}" --once'
```

Tests, no robot needed:

```shell
docker compose run --rm unitree_ros bash -c 'python3 -m pytest /ros2_ws/src/go2_auto_mapper/test'
```

<!-- sources: src/go2_auto_mapper/README.md, go2_auto_mapper/explorer.py (subscriptions, action clients, /cmd_vel_mapper), obstacle_sensing.py, frontier_scoring.py, src/go2_robot_sdk/config/twist_mux.yaml, src/go2_rviz_plugins/src/auto_mapper_panel.cpp, docs/USEFUL_COMMANDS.md, AGENTS.md, docs/FUSION.md, git log Oct 14-19 (commits 7ebad74, 6bf385f, 1973d50, 7b3a8e7, 9b9e25b, 264939b, a51627d), contract team updates (Luis) -->
