---
title: Lidar
parent: senses
code: [src/lidar_processor/**, src/lidar_processor_cpp/**, src/go2_robot_sdk/go2_robot_sdk/infrastructure/sensors/lidar_decoder.py]
---

# Lidar

The driver publishes `/point_cloud2`; `lidar_processor` (Python and C++) aggregates and filters it, and `pointcloud_to_laserscan` turns it into `/scan`.

Part of: [Senses](senses.md)

## Related

- [SLAM](slam.md)

## Code

- `src/lidar_processor/**`
- `src/lidar_processor_cpp/**`
- `src/go2_robot_sdk/go2_robot_sdk/infrastructure/sensors/lidar_decoder.py`

<!-- TODO: content -->
