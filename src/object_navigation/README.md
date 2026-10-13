# object_navigation

Drives the robot toward an object that `object_detection` has seen. Publish an object ID
like `chair_1` and the robot turns toward it and walks until it is about 0.5 m away.

Written by Riley Francis in [ROS2-LLM-Nav](https://github.com/RileyFrancis/ROS2-LLM-Nav).

**It has no obstacle avoidance.** It drives in a straight line toward a rough position
estimate. That is why it has the lowest twist_mux priority: the joystick, keyboard, Nav2
and the LLM agent all override it. Only run it with someone watching the robot.

## Run

Inside the container, with the robot stack and `object_detection` running:

```shell
ros2 run object_navigation navigation_node
ros2 topic echo /detected_objects_dict                                  # pick an ID
ros2 topic pub /navigate_to_object std_msgs/String "data: 'chair_1'" --once
```

To stop it, drive with the keyboard or joystick (they override it), or Ctrl+C the node.

## Topics

| Direction | Topic | Type | What |
| --- | --- | --- | --- |
| Subscribes | `/detected_objects_dict` | `std_msgs/String` | Object memory (JSON) from `object_detection` |
| Subscribes | `/navigate_to_object` | `std_msgs/String` | Target object ID, such as `chair_1` |
| Publishes | `/cmd_vel_object_nav` | `geometry_msgs/Twist` | Drive command, 10 Hz (its own twist_mux input, priority 3) |

## How it works

Every 0.1 s, while it has a target:

1. If the target is gone from the detector's memory, stop and drop it.
2. Turn toward it: `angular.z = 1.5 * angle`, capped at 1.0 rad/s.
3. Only walk forward when roughly facing it (angle under 0.3 rad):
   `linear.x = 0.5 * distance`, capped at 0.4 m/s.
4. Stop when closer than 0.5 m.

## Limits

- No obstacle avoidance, no map, no Nav2, no TF lookup.
- Assumes object positions are already in the robot's frame, and they are only as good as
  `object_detection`'s rough estimate.
- The target must be an exact ID from `/detected_objects_dict`. Objects are forgotten
  20 seconds after the detector last saw them.
