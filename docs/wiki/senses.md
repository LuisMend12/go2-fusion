---
title: Senses
parent: oak
---

# Senses

What Oak perceives: lidar, camera, its body frames, and computer vision on the camera feed.

Part of: [Oak](../../README.md)

## Pages

- [Lidar](lidar.md) - The driver publishes `/point_cloud2`; `lidar_processor` (Python and C++) aggregates and filters it, and `pointcloud_to_laserscan` turns it into `/scan`.
- [Camera](camera.md) - The driver publishes the front camera on `/camera/image_raw`.
- [TF and robot model](tf.md) - The URDF robot model and the transform tree that places Oak's body, legs and sensors relative to each other, fed by `/joint_states` and `/odom`.
- [Object detection](object-detection.md) - Computer vision on the camera feed: YOLOv8 `object_detection` with rough positions and a 20 s memory, plus the older MobileNet `coco_detector` that is to be retired.

<!-- TODO: content -->
