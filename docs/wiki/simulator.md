---
title: Simulator
parent: lab-setup
code: [src/go2_sim/**]
---

# Simulator

The simulator is a pretend Oak in a pretend flat, inside Gazebo (a robot simulator). It lets anyone test the [auto mapper](auto-mapper.md), [SLAM](slam.md) and [Nav2](nav2.md) on a laptop, with no robot and no lab, and run the auto mapper many times in a row to see how often it finishes.

Part of: [Lab setup](lab-setup.md)

## How it works

**No legs, on purpose.** Oak's own computer does the walking; our code only ever tells it "go this fast forward, sideways and turning". So the simulated Oak is one Go2-sized box (0.70 x 0.31 m) that Gazebo slides around at the commanded speed, sideways included. That is what our stack can tell apart, and it is much faster and steadier than simulating legs.

**Same wiring as the real robot.** The simulator starts the real stack, `robot.launch.py`, with one change: the [Go2 driver](go2-driver.md) is swapped for a stand-in, `sim_driver`. The stand-in speaks the driver's topics:

- it takes commands from `/cmd_vel_out` ([twist_mux](twist-mux.md)'s output) and passes them to Gazebo after a short delay;
- it publishes `/odom` and the `odom` -> `base_link` link of the [TF tree](tf.md), with made-up step-counting error added;
- it publishes `/point_cloud2` in the `odom` frame, like the real driver, from a simulated lidar under Oak's chin (where `go2.urdf` puts it); `pointcloud_to_laserscan` turns it into `/scan` as usual;
- it publishes a standing `/joint_states`, so RViz draws the legs.

So SLAM, Nav2, twist_mux and the auto mapper run unchanged. `/imu`, `/go2_states` and the camera are not simulated. The cloud reaches `lidar_to_pointcloud` through the same `/robot0/point_cloud2` -> `/point_cloud2` rename as on the robot (the open topic question in the [Test log](test-log.md) applies here too).

**Kept away from the real robot.** The simulator uses ROS domain 42 and talks only inside your computer (`ROS_LOCALHOST_ONLY=1`), so its drive commands can never reach a real Oak on the network. To look at its topics from another terminal, first run `export ROS_DOMAIN_ID=42 ROS_LOCALHOST_ONLY=1`.

**The world.** `placeholder_rooms` is a made-up 10 x 8 m flat: four rooms, 1.2 m doorways, two routes round (so SLAM can close a loop), a few furniture boxes and a pillar. It is not the lab. Jeth is building a tape-measured lab world (issue #28); any world drops in with `world:=`.

## Watch one run (with windows)

You need RViz windows working first ([WSL and Windows](wsl.md) or [Mac setup](mac-setup.md)). Then:

```shell
cd docker
docker compose -p go2fusion run --rm unitree_ros ros2 launch go2_sim sim.launch.py gui:=true explore:=true
```

The Gazebo window shows Oak in the flat; RViz shows the map growing. `explore:=true` starts the auto mapper right away. Leave it out to drive yourself (keyboard teleop in a second terminal, with the domain set as above). Start somewhere else with `x:=7.5 y:=7.0 yaw:=1.57`. Closing Gazebo stops everything.

## Run many trials (headless)

```shell
cd docker
docker compose -p go2fusion run --rm unitree_ros ros2 run go2_sim trials
```

This runs the auto mapper 10 times with no windows. Each run starts a fresh simulator at a random start spot (the same spots every time for the same `--seed`), waits for Nav2, starts the auto mapper, and stops at "Exploration complete", after 15 minutes, or when Oak is stuck (moved less than 0.25 m in 3 minutes). It then prints one row per run plus totals:

- **Map complete**: how much of the flat's floor the SLAM map has seen, compared with a true map built from the world file.
- **Time**: from the auto mapper starting to "Exploration complete".
- **Collisions**: separate bumps of Oak's body against walls or furniture (a touch sensor on the body).
- **Distance**: how far Oak really walked.
- **Finished**: yes if the auto mapper said it was done. Otherwise the note says why it stopped and where Oak ended up, so you can find the trouble spot.

Results land in `src/go2_sim/results/<date-time>/` on your laptop (git ignores it): `results.csv`, `results.md` (the table), each run's final map, and logs. Options: `--runs 3`, `--timeout 600`, `--stall-timeout 300` (0 = never), `--seed 2`, `--world <name or .sdf>`. Dials go after `--`, for example `ros2 run go2_sim trials --runs 5 -- lidar_rate:=2.0 odom_noise_xy:=0.05`.

## Watch the trials live

The trials run headless, but you can look in on them. Start the trials in a named container, then attach windows from a second terminal:

```shell
cd docker
docker compose -p go2fusion run --rm --name oak-trials unitree_ros ros2 run go2_sim trials
docker exec -it oak-trials bash -ic 'ros2 run go2_sim watch'     # second terminal
```

`watch` opens a Gazebo window and RViz on whichever run is going, and moves to the next run when one ends (`--no-rviz` for Gazebo only). It only looks: closing it, or never opening it, does not change the runs. It needs RViz windows working ([WSL and Windows](wsl.md)).

## The dials

Launch arguments (for `sim.launch.py`, or after `--` for trials). The odometry and command ones live in `src/go2_sim/config/sim.yaml` with a few more.

| Dial | Default | What it does |
| --- | --- | --- |
| `world` | `placeholder_rooms` | Which world: a name in `src/go2_sim/worlds/` or a path to an `.sdf` file |
| `x`, `y`, `yaw` | 2.5, 2.0, 0 | Start spot in the world (m, m, radians) |
| `gui` | `false` | Open the Gazebo window; also opens RViz unless `rviz:=false` |
| `explore` | `false` | Start the auto mapper at once |
| `lidar_rate` | 5 | Lidar scans per second. Measured on Oak: 3 to 6.8 for the cloud, 4 to 5 for `/scan` ([Driver](driver.md), [Test log](test-log.md)). Try 2 for a bad day |
| `lidar_range` | 12 | Farthest the lidar sees (m) |
| `odom_noise_xy` | 0.01 | Random step-counting error: about 1 cm after 1 m, 5 cm after 25 m |
| `odom_noise_yaw` | 0.01 | Random turning error, the same idea for turns |
| `odom_drift_yaw` | 0 | Steady heading drift, radians per meter walked (a slow curve SLAM has to fix) |
| `cmd_latency` | 0.1 | Seconds between a drive command and Oak moving |
| `seed` | 0 | Odometry noise seed (0 = different every run) |

In `sim.yaml` only: `odom_scale_xy` and `odom_scale_yaw` (Oak says it went or turned a few % more than it did), `cmd_timeout` (Oak stops after 0.5 s without commands), speed and acceleration limits, the lidar mount position, and the self-filter box that drops lidar points on Oak's own head and legs (kept inside the 0.36 m nose, so something touching the nose is still seen). TODO(owner): measure Oak's real odometry error, command delay and stop timeout, and set these defaults from them.

## Adding a world

Put the `.sdf` file anywhere and pass `world:=/ros2_ws/src/<path>.sdf`. Two rules: build it for Gazebo Fortress, and make walls and furniture boxes or cylinders, because the true map for scoring is built from those. A world made of meshes (for example a 3D scan) needs a true map shipped next to it as `<world>.gt.yaml` plus `.pgm`, in the same format the map saver writes. `ros2 run go2_sim ground_truth <world>` writes the true map, so you can open the picture and check it.

## What it found so far

First 10-run batch (2026-10-28, placeholder world, default dials, real-time factor 1.0): mean map completeness 78 % (48 to 99.5 %), 1 of 10 finished, 0 collisions, about 4.5 minutes per run. Eight of the nine unfinished runs ended stuck in or beside a 1.2 m doorway; real doors are narrower.

- **Nav2 never re-sent the full local costmap while Oak stood still**, so the auto mapper stalled after its first scan ("timed out waiting for fresh costmap"). Fixed in `nav2_params.yaml` (see [Nav2](nav2.md)); still to confirm on Oak.
- **Oak latched stopped next to the first close obstacle.** The auto mapper's unstuck move said "no safe direction" and waited forever, even with open floor behind. The lidar there reads true distances (checked beam by beam against the true map). Three bugs in the auto mapper's check caused it, all fixed (see [Auto mapper](auto-mapper.md)), still to confirm on Oak.
- **Nav2 drives Oak to within 0.05-0.25 m of door jambs, the pillar and furniture**, then reports "No valid trajectories" or "Failed to make progress". With the recovery fixes Oak can back off more often, but some runs still end stuck in a doorway or corner. TODO(Luis): does Oak get that close on the real floor? If so, Nav2's obstacle weighting (DWB `ObstacleFootprint.scale` 0.02) is the place to look.
- **`go2.urdf`'s fixed `odom` -> `base_link` joint** puts `base_link` on the floor until odometry starts; a lidar cloud sent before then shows the floor as walls. The stand-in driver now waits for odometry first. The real driver might hit the same thing at startup (see [TF and robot model](tf.md)).

## How it breaks

- **"Gazebo's `ign` command is missing".** The image is older than the simulator: run `docker compose build`.
- **No lidar, startup timeout.** The headless lidar needs a working graphics library inside the container. The trial log says `startup timeout: no lidar on /point_cloud2`; look at `logs/run_01_launch.log`. TODO(owner): confirm on a machine without an NVIDIA card.
- **Runs slower than real time.** The auto mapper's waits are in wall-clock seconds, so a slow simulator makes it give up early. The trial runner prints a real-time factor per run; below about 0.9, close other programs or run fewer things at once.
- **It is kinder than the real Oak.** Perfectly flat floor, no people, no glass or mirrors, a cleaner lidar, and a body that slides instead of stepping. A good trial score is a first check, not proof; confirm on Oak and log it in the [Test log](test-log.md).
- **Collisions push, not stop.** Gazebo keeps pushing Oak at the commanded speed while it touches a wall, so one long scrape counts as one bump.
- **The RViz AutoMapper panel works** (it starts the auto mapper in the simulator's domain), but its Reset maps button restarts SLAM, which makes that run's score meaningless.

## Who's on it and what's next

Max added the simulator (branch `feat/go2-sim`). Next: Jeth's lab world (issue #28) in place of the placeholder, and real odometry and lidar numbers from Oak for the dials. TODO(owner): an owner for the simulator.

## The code

https://github.com/maxhawksby/go2-fusion/tree/master/src/go2_sim (`launch/sim.launch.py` starts it all; `go2_sim/sim_driver.py` is the stand-in driver; `go2_sim/trials.py` the trial runner; `go2_sim/world_tools.py` builds the true map and scores runs; `worlds/` and `models/oak/` are the Gazebo files.)

Unit tests (no Gazebo needed):

```shell
docker compose -p go2fusion run --rm unitree_ros bash -c 'python3 -m pytest /ros2_ws/src/go2_sim/test'
```

<!-- sources: src/go2_sim/** (this branch), src/go2_robot_sdk/launch/robot.launch.py (driver arg), go2_driver_node.py and ros2_publisher.py (topics, odom frame), urdf/go2.urdf (radar_joint), config/nav2_params.yaml (footprint), config/twist_mux.yaml, docs/wiki/driver.md and test-log.md (lidar rates), docs/wiki/auto-mapper.md ("Exploration complete") -->
