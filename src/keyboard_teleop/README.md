# keyboard_teleop

Drive the Go2 from a terminal keyboard instead of a joystick. Publishes
`geometry_msgs/msg/Twist` to `/cmd_vel_keyboard`, the keyboard input of
`twist_mux` (priority 9: only the joystick overrides it, and it overrides Nav2
and the autonomous nodes). See `go2_robot_sdk/config/twist_mux.yaml`.

## Prerequisites

The main robot stack must already be running and connected to the robot
(either the native WSL2 install or the Docker container), since
`keyboard_teleop` only sends movement commands — it doesn't connect to the
robot itself.

## Run it (native WSL2 install)

Open a terminal and start an interactive WSL session:

```shell
wsl -d Ubuntu-22.04
```

Inside that shell:

```shell
source /opt/ros/humble/setup.bash
source ~/ros2_ws/install/setup.bash
ros2 run keyboard_teleop keyboard_teleop
```

## Run it (Docker)

```shell
docker exec -it docker-unitree_ros-1 bash
```

Inside the container:

```shell
ros2 run keyboard_teleop keyboard_teleop
```

## Controls

| Key | Action |
|---|---|
| `W` / `S` | Forward / backward |
| `A` / `D` | Turn left / right |
| `Q` / `E` | Strafe left / right |
| `Z` / `X` | Decrease / increase speed |
| `Space` | Stop |
| `Esc` | Quit |

Keys can be combined in sequence — e.g. hold `W`, tap `D`, to curve while
moving forward. Each direction key stays active for about 0.4 seconds after
it's last pressed, then that axis automatically zeroes out, so releasing a
key (or walking away from the keyboard) brings the robot to a stop on its
own even without pressing Space.

Requires a real terminal (an interactive session, not a piped/redirected
one) — it will log an error and do nothing if stdin isn't a TTY.

## Rebuilding after changes

If you edit `keyboard_teleop.py`, rebuild just this package rather than the
whole workspace:

**WSL2:**
```shell
cd ~/ros2_ws
colcon build --packages-select keyboard_teleop
```

**Docker:** nothing to rebuild. The repo is mounted into the container and
built with `--symlink-install`, so just quit (`Esc`) and rerun `teleop`.
See [CONTRIBUTING.md](../../CONTRIBUTING.md#the-edit-loop).
