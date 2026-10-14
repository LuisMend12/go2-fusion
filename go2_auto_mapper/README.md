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
3. It scores each region by distance (closer is better) and size (bigger
   is better). The goal is a known-free cell `goal_distance` meters back
   from that region's center, toward the robot, so Nav2 is not asked to
   stop on the unknown boundary.
4. The goal is sent to Nav2's `/navigate_to_pose` action — Nav2 plans the
   path and drives there, same as any manually-set goal.
5. Once the map has no frontiers left, it logs "Exploration complete" and
   stops sending goals (it keeps watching, in case new frontiers appear
   later — e.g. after a door opens or the robot is manually moved).

If Nav2 rejects or fails a goal (e.g. it was too close to an obstacle), that
spot is blacklisted for 30 seconds so the explorer doesn't immediately
retry the same bad location forever.

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
| `scan_on_start` | `true` | Turn a full circle before exploring |
| `scan_after_goal` | `true` | Turn a full circle after each goal it reaches |
| `scan_yaw` | `6.283` (2π) | How far to turn per scan, in radians |
| `scan_time_allowance` | `30.0` | Seconds Nav2 has to finish the turn before giving up |

Override at launch, e.g.:
```shell
ros2 run go2_auto_mapper explorer --ros-args -p min_frontier_size:=10
```

## Known limitations

- `front_leg_controller` is a separate, currently-inert placeholder package
  (not part of this one) — it logs simulated leg motion but never sends
  real commands.
- Frontier detection rescans the entire map every cycle, so very large
  maps will make each exploration step progressively slower.
