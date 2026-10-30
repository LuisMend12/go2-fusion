#!/usr/bin/env python3
"""Shows what the VLM sees: asks it to describe the camera every few seconds.

A node of its own because the explorer drives the robot, and this should work
with the robot standing still. It only reads the camera and publishes text and
pictures, never a motion command. The RViz AutoMapper panel's VLM view button
starts it and shows /vlm/view and /vlm/description.
"""

import os
import threading

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import String

from go2_auto_mapper.explorer import encode_jpeg, stop_when_parent_dies
from go2_auto_mapper.vlm_ranking import build_describe_request, post_chat

DEFAULT_URL = 'http://localhost:8000/v1/chat/completions'
DEFAULT_MODEL = 'Qwen/Qwen2.5-VL-7B-Instruct'


class VlmView(Node):

    def __init__(self):
        super().__init__('vlm_view')
        self.declare_parameter('vlm_url', os.environ.get('VLM_URL', DEFAULT_URL))
        self.declare_parameter('vlm_model', os.environ.get('VLM_MODEL', DEFAULT_MODEL))
        self.declare_parameter('period_sec', 5.0)
        self.declare_parameter('timeout_sec', 90.0)   # the first answer loads the model
        self.url = self.get_parameter('vlm_url').value
        self.model = self.get_parameter('vlm_model').value
        self.timeout = self.get_parameter('timeout_sec').value
        self.api_key = os.environ.get('VLM_API_KEY')

        self.frame = None
        self.busy = False
        camera_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.create_subscription(Image, '/camera/image_raw', self.camera_callback, camera_qos)
        # Latched, so the panel gets the last answer whenever it subscribes.
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.view_pub = self.create_publisher(CompressedImage, '/vlm/view', latched)
        self.text_pub = self.create_publisher(String, '/vlm/description', latched)
        self.create_timer(self.get_parameter('period_sec').value, self.ask)
        self.get_logger().info(f'Describing the camera with {self.model} at {self.url}.')

    def camera_callback(self, msg):
        self.frame = msg

    def ask(self):
        """One request at a time, off the spin thread: answers can take a while."""
        if self.busy or self.frame is None:
            return
        frame, self.frame = self.frame, None
        self.busy = True
        threading.Thread(target=self.describe, args=(frame,), daemon=True).start()

    def describe(self, frame):
        try:
            jpeg = encode_jpeg(frame)
            view = CompressedImage(format='jpeg', data=jpeg)
            view.header = frame.header
            self.view_pub.publish(view)
            payload = build_describe_request(self.model, jpeg)
            text = post_chat(self.url, payload, self.timeout, self.api_key)
        except Exception as e:   # a down server must not end the node
            text = f'VLM not answering: {e}'
            self.get_logger().warn(text, throttle_duration_sec=30.0)
        self.text_pub.publish(String(data=text))
        self.busy = False


def main(args=None):
    stop_when_parent_dies()
    rclpy.init(args=args)
    node = VlmView()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
