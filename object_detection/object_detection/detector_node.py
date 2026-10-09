import rclpy
from rclpy.node import Node

from sensor_msgs.msg import Image
from geometry_msgs.msg import PoseStamped
from std_msgs.msg import String

from cv_bridge import CvBridge
from ultralytics import YOLO
from rclpy.qos import qos_profile_sensor_data
from ament_index_python.packages import get_package_share_directory

import numpy as np
import json
import math
import os


class ObjectDetector(Node):

    def __init__(self):
        super().__init__("object_detector")

        self.bridge = CvBridge()
        # Defaults to the weights installed with this package; override with
        # `--ros-args -p model_path:=/path/to/weights.pt`.
        default_model = os.path.join(
            get_package_share_directory("object_detection"), "models", "yolov8n.pt"
        )
        model_path = self.declare_parameter("model_path", default_model).value
        self.get_logger().info(f"Loading YOLO model from {model_path}")
        self.model = YOLO(model_path)

        # Subscribe to RGB
        self.rgb_sub = self.create_subscription(
            Image,
            "/camera/image_raw",
            self.rgb_callback,
            qos_profile_sensor_data
        )

        # Publishers
        self.annotated_pub = self.create_publisher(
            Image,
            "/detections/image_annotated",
            10
        )

        # Not /detected_objects: coco_detector already publishes
        # vision_msgs/Detection2DArray there, and two message types on one
        # topic break both.
        self.object_pose_pub = self.create_publisher(
            PoseStamped,
            "/detected_objects/poses",
            10
        )

        self.dict_pub = self.create_publisher(
            String,
            "/detected_objects_dict",
            10
        )

        # Persistent memory
        self.object_map = {}

        # Horizontal camera FOV (approximate)
        self.horizontal_fov = np.deg2rad(90)

        # Object expiry time (seconds)
        self.expiry_time = 20

        self.get_logger().info("RGB object detector with memory ready")

    # ==========================================================
    # Main Callback
    # ==========================================================
    def rgb_callback(self, msg):

        frame = self.bridge.imgmsg_to_cv2(msg, "bgr8")
        results = self.model(frame)

        # Publish annotated image
        annotated = results[0].plot()
        annotated_msg = self.bridge.cv2_to_imgmsg(annotated, encoding="bgr8")
        self.annotated_pub.publish(annotated_msg)

        image_width = frame.shape[1]
        image_height = frame.shape[0]

        current_time = self.get_clock().now().nanoseconds / 1e9

        # Process detections
        for box in results[0].boxes:

            cls = int(box.cls[0])
            label = self.model.names[cls]

            x1, y1, x2, y2 = box.xyxy[0]

            center_x = (x1 + x2) / 2
            box_height = (y2 - y1)

            # Angle calculation
            normalized_x = (center_x - image_width / 2) / (image_width / 2)
            angle = normalized_x * (self.horizontal_fov / 2)

            # Rough distance estimate
            distance_estimate = 1.0 / (box_height / image_height + 1e-6)

            x_pos = float(distance_estimate * math.cos(angle))
            y_pos = float(distance_estimate * math.sin(angle))

            matched_id = None

            # Try matching existing objects of same class
            for obj_id, obj_data in self.object_map.items():

                if not obj_id.startswith(label):
                    continue

                dx = obj_data["x"] - x_pos
                dy = obj_data["y"] - y_pos
                dist = math.sqrt(dx*dx + dy*dy)

                if dist < 0.5:  # match threshold (meters approx)
                    matched_id = obj_id
                    break

            # If no match, create new ID
            if matched_id is None:
                index = sum(1 for k in self.object_map if k.startswith(label)) + 1
                matched_id = f"{label}_{index}"

            # Update memory
            self.object_map[matched_id] = {
                "x": round(x_pos, 2),
                "y": round(y_pos, 2),
                "last_seen": current_time
            }

            # Publish pose for RViz
            pose = PoseStamped()
            pose.header.frame_id = "base_link"
            pose.header.stamp = self.get_clock().now().to_msg()

            pose.pose.position.x = x_pos
            pose.pose.position.y = y_pos
            pose.pose.position.z = 0.0

            self.object_pose_pub.publish(pose)

        # Expire old objects
        to_delete = []

        for obj_id, obj_data in self.object_map.items():
            if current_time - obj_data["last_seen"] > self.expiry_time:
                to_delete.append(obj_id)

        for obj_id in to_delete:
            del self.object_map[obj_id]

        # Publish dictionary without timestamps
        clean_dict = {
            k: {"x": v["x"], "y": v["y"]}
            for k, v in self.object_map.items()
        }

        json_msg = String()
        json_msg.data = json.dumps(clean_dict)
        self.dict_pub.publish(json_msg)

        if clean_dict:
            self.get_logger().info(f"Memory: {clean_dict}")


def main():
    rclpy.init()
    node = ObjectDetector()
    rclpy.spin(node)
    rclpy.shutdown()