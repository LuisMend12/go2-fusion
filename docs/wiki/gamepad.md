---
title: Gamepad
parent: driving
code: [src/go2_robot_sdk/config/joystick.yaml]
---

# Gamepad

The gamepad lets a person drive Oak with a game controller (an Xbox-style pad) and always outranks every other drive source, as long as a safety button is held.

Part of: [Driving](driving.md)

## How it works

Two standard ROS programs do the work, both started by the default launch file `robot.launch.py`:

1. **`joy_node`** (package `joy`) reads the controller plugged into your computer and publishes its sticks and buttons on `/joy`.
2. **`teleop_twist_joy`** (node name `go2_teleop_node`) turns those sticks into velocity commands (`geometry_msgs/Twist`) on `/cmd_vel_joy`.

`/cmd_vel_joy` is the top lane in [twist_mux](twist-mux.md), priority 10, so a held gamepad beats the keyboard, Nav2 and everything else.

The safety button is called a **deadman button**: the pad drives only while you hold it, and sends nothing when you let go.
`joystick.yaml` sets it to LB (button 4 on an Xbox controller).
Without it, an idle pad repeats "speed 0" about 20 times a second, which used to freeze the agent and object navigation.

`joystick.yaml` also sets which stick axes drive: forward from axis 1 and sideways from axis 3 (both scaled to 0.5 m/s), turning from axis 6 (scaled to 1.0 rad/s), and a 0.05 dead zone so a resting stick reads zero.

Separately, the [Go2 driver](go2-driver.md) also reads `/joy` itself: button 0 sends Stand Up and button 1 sends Stand Down. These go straight to the robot, not through twist_mux.

## Connects to

- [twist_mux](twist-mux.md): `/cmd_vel_joy`, priority 10.
- [Go2 driver](go2-driver.md): reads `/joy` for stand up / stand down.
- Launch switch: `joystick:=false` turns off `joy_node` and `teleop_twist_joy`.

## How it breaks

- **Never tested on Oak.** The lab has no Xbox-style pad; it uses Unitree's own remote, which talks to the robot directly and bypasses ROS. The deadman logic was tested only in Docker with simulated input.
- **The deadman setting may not be applied.** All four launch files that start `teleop_twist_joy` give it `twist_mux.yaml` as its settings, not `joystick.yaml`. The `go2_teleop_node` section (LB, axes, scales) lives in `joystick.yaml`, so the node may be running on the package's built-in defaults instead. TODO(owner): check with `ros2 param get /go2_teleop_node enable_button` and fix the launch files if it is not 4.
- **On Windows without WSL** there is no `/dev/input`, so the container cannot see a controller at all (see [WSL and Windows](wsl.md)).

## Who's on it and what's next

TODO(owner): no one owns the gamepad. Open follow-up from the fusion: with a real Xbox controller, confirm LB is button 4 (`ros2 topic echo /joy`) and that letting go stops the dog.

## The code

Config: https://github.com/maxhawksby/go2-fusion/tree/master/src/go2_robot_sdk/config

Check it without the robot, on a Linux or WSL host with the pad plugged in (the default compose file maps `/dev/input` into the container):

```shell
docker compose exec unitree_ros bash -ic 'ros2 topic echo /joy'
docker compose exec unitree_ros bash -ic 'ros2 topic echo /cmd_vel_joy'
```

Press buttons to learn their numbers in the first; hold LB and move a stick to see commands in the second.

<!-- sources: src/go2_robot_sdk/config/joystick.yaml; src/go2_robot_sdk/launch/robot.launch.py, robot_cpp.launch.py, navigation.launch.py, mapping.launch.py (teleop_node parameters=twist_mux); src/go2_robot_sdk/application/services/robot_control_service.py handle_joy_command; presentation/go2_driver_node.py joy subscription; docker/docker-compose.yml devices; docs/WINDOWS_SETUP.md "Why a separate compose file"; docs/FUSION.md row 13 and follow-up 5; docs/TEST_LOG.md "Gamepad LB deadman: not run" -->
