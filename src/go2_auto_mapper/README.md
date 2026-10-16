# go2_auto_mapper

Autonomous frontier-exploration mapper for the Go2. Reads the live SLAM map,
finds unexplored boundary regions ("frontiers"), and drives the robot there
via Nav2 — the same mechanism as manually clicking "Nav2 Goal" in RViz, so
it doesn't bypass Nav2's own obstacle avoidance.

**This moves the robot on its own.** Only run it when you're physically
present, watching the robot, in a cleared area.

## Prerequisites

The main robot stack must already be running (SLAM + Nav2 active), either
via the native WSL2 install or Docker.

## Run it (native WSL2 install)

```shell
wsl -d Ubuntu-22.04
source /opt/ros/humble/setup.bash
source ~/ros2_ws/install/setup.bash
ros2 run go2_auto_mapper explorer
```

## Run it (Docker)

```shell
docker exec -it docker-unitree_ros-1 bash
ros2 run go2_auto_mapper explorer
```

## How it works

0. On start, and again after each goal it reaches, the robot turns a full
   circle in place through Nav2's spin behavior (which checks the local
   costmap for obstacles). The 360 degree lidar view lets SLAM place the
   robot on the map. Until SLAM publishes the `map` frame, the explorer
   logs "Waiting for robot position" and does nothing else.
1. Every 2 seconds, it scans the current map for frontier cells — free
   space directly adjacent to unexplored (unknown) space.
2. Frontier cells are clustered into regions; regions smaller than
   `min_frontier_size` (default 5 cells) are ignored as noise.
3. Each region offers target points (its middle, plus one about every
   meter along long regions). The goal for a point is a known-free cell
   `goal_distance` meters back toward the robot, at least `wall_clearance`
   from any wall, so Nav2 is not asked to stop on the unknown boundary or
   against a wall.
4. It picks a goal in this order of priority: not toward a direction it was
   just blocked in; at least `min_goal_distance` away; a straight line to it
   that is clear in Nav2's local costmap (`/local_costmap/costmap`, which
   merges the 2D scan and the 3D point cloud); then nearest and largest.
5. The goal is sent to Nav2's `/navigate_to_pose` action — Nav2 plans the
   path and drives there, same as any manually-set goal.
6. While driving, it checks the local costmap 4 times a second for an
   obstacle within `obstacle_stop_distance` of the robot's nose, in a strip
   as wide as its body. If one stays there for `blocked_timeout` seconds,
   it cancels the goal, backs up `backup_distance`, and for the next 30
   seconds avoids that heading and prefers the longest open walk on offer.
7. **When stuck, it heads for open space.** Stuck means `stuck_failure_count`
   (3) goals failed in a row, an obstacle-ahead abort, or "No usable goal"
   twice running. It then finds the nearest known-free spot with at least
   `open_space_clearance` (0.8 m) of room on every side, searching through
   free space up to 4 m away (so not through walls), drives there, scans,
   and carries on exploring. A failed escape doesn't trigger another one,
   and escapes are at least 30 s apart.
8. Once the map has no frontiers left, it logs "Exploration complete" and
   stops sending goals (it keeps watching, in case new frontiers appear
   later — e.g. after a door opens or the robot is manually moved).

To scan on demand, press **Scan** in the RViz AutoMapper panel, or:
```shell
ros2 service call /frontier_explorer/scan std_srvs/srv/Trigger
```
It pauses the current goal (without counting it as failed), forgets
recently failed spots so they get another try with the fresh data, and
turns 360 degrees. Useful when the explorer reports "No usable goal".

If Nav2 rejects or fails a goal (e.g. it was too close to an obstacle), that
spot is blacklisted for 2 minutes so the explorer doesn't keep retrying the
same bad locations.

## Stopping it

**If it's running in the foreground of your terminal:** press `Ctrl+C`.
This cancels any in-flight Nav2 goal and waits briefly for that
cancellation to actually reach Nav2 before exiting, so the robot doesn't
keep walking toward a goal nobody is tracking anymore.

**If it's running in the background** (e.g. started with `nohup ... &`,
like during development/testing), stop it from another terminal:

```shell
pkill -f 'go2_auto_mapper/lib/go2_auto_mapper/explorer'
```

Then, as a safety net regardless of how it was stopped, you can force an
immediate stop and cancel any still-active Nav2 goal directly:

```shell
ros2 service call /navigate_to_pose/_action/cancel_goal action_msgs/srv/CancelGoal "{}"
ros2 topic pub /cmd_vel_joy geometry_msgs/msg/Twist "{}" --once
```

The `cmd_vel_joy` publish works because `twist_mux` treats it as the
highest-priority input (same priority tier as a joystick), so it overrides
whatever Nav2 was commanding.

## Parameters

| Parameter | Default | Meaning |
|---|---|---|
| `map_topic` | `/map` | Occupancy grid topic to read |
| `robot_frame` | `base_link` | TF frame for the robot's position |
| `map_frame` | `map` | TF frame the map is published in |
| `min_frontier_size` | `5` | Minimum cluster size (in cells) to count as a real frontier |
| `goal_distance` | `0.8` | How far inside known space, toward the robot, to place the goal |
| `min_goal_distance` | `1.5` | Skip goals closer than this (meters) while any farther frontier is left |
| `wall_clearance` | `0.5` | Skip goal spots closer than this (meters) to a wall in the SLAM map |
| `obstacle_stop_distance` | `0.3` | Gap (meters) in front of the nose that counts as blocked |
| `blocked_timeout` | `2.0` | Seconds blocked before giving up the goal (a brief glance at a wall while turning is normal) |
| `backup_distance` | `0.3` | How far (meters) to back up after giving up a blocked goal |
| `open_space_clearance` | `0.8` | Room (meters) on every side that counts as open space when stuck |
| `stuck_failure_count` | `3` | Failed goals in a row that count as stuck |
| `scan_on_start` | `true` | Turn a full circle before exploring |
| `scan_after_goal` | `true` | Turn a full circle after each goal it reaches |
| `scan_yaw` | `6.283` (2π) | How far to turn per scan, in radians |
| `scan_time_allowance` | `30.0` | Seconds Nav2 has to finish the turn before giving up |

Override at launch, e.g.:
```shell
ros2 run go2_auto_mapper explorer --ros-args -p min_frontier_size:=10
```

## Known limitations

- `front_leg_controller` (the `front_leg_controller.py` node specifically)
  is a separate, currently-inert placeholder (not part of this one) — it
  logs simulated leg motion but never sends real commands. The same
  package's other node, `sit_controller.py`, is **not** inert — it sends a
  real Sit command (API 1009) to `/webrtc_req`.
- Frontier detection rescans the entire map every cycle, so very large
  maps will make each exploration step progressively slower.
