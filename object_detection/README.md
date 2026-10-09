# object_detection

Finds objects in the robot's camera feed with YOLOv8 (the small "nano" model) and keeps a
short memory of where they are, so other nodes can ask "where is `chair_1`?".

Written by Riley Francis in [ROS2-LLM-Nav](https://github.com/RileyFrancis/ROS2-LLM-Nav).
See [FUSION.md](../FUSION.md) for what changed when it was brought into this repo.

## Run

Inside the container, with the robot stack (and so the camera) running:

```shell
ros2 run object_detection detector_node
ros2 topic echo /detected_objects_dict      # in another terminal
```

You should see JSON like `{"chair_1": {"x": 2.1, "y": -0.3}}`.

## Topics

| Direction | Topic | Type | What |
| --- | --- | --- | --- |
| Subscribes | `/camera/image_raw` | `sensor_msgs/Image` | Camera frames from the driver |
| Publishes | `/detections/image_annotated` | `sensor_msgs/Image` | Camera frame with boxes and labels drawn on it |
| Publishes | `/detected_objects/poses` | `geometry_msgs/PoseStamped` | Rough position of each detection, frame `base_link` (no label) |
| Publishes | `/detected_objects_dict` | `std_msgs/String` | JSON memory: object ID to rough `x`/`y` in meters |

`/detected_objects/poses` was `/detected_objects` in Riley's repo. It was renamed because
`coco_detector` publishes a different message type on `/detected_objects`.

## How it works

1. Runs YOLO on every camera frame.
2. Turns each box into a rough position: the angle comes from where the box sits left to
   right in the image (assuming a 90 degree field of view), and the distance is
   `1 / (box height / image height)`, so bigger boxes count as closer.
3. A new detection within about 0.5 m of a remembered object of the same class reuses its
   ID; otherwise it gets the next ID (`chair_1`, `chair_2`, ...).
4. Objects not seen for 20 seconds are forgotten.

## Parameters

| Parameter | Default | Meaning |
| --- | --- | --- |
| `model_path` | `share/object_detection/models/yolov8n.pt` | YOLO weights file |

Try other weights without rebuilding:
`ros2 run object_detection detector_node --ros-args -p model_path:=/path/to/weights.pt`.
To change the default, add the file to `models/`, list it in `setup.py` `data_files`, and
update the default in `detector_node.py`.

## Limits

- Positions are very rough: no depth camera, no camera calibration, no TF lookup.
- No confidence threshold of its own; it trusts every box YOLO returns.
- On CPU it runs every frame with no throttling and logs the memory every frame, so expect
  lag and a noisy log.
- `ultralytics` downloads a font file the first time it draws boxes, so the container
  needs internet on first run.
- Needs `ultralytics` from pip; it is in the repo's `requirements.txt`, so the Docker image
  has it.
