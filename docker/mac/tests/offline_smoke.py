"""Run inside the Mac container; synthetic sensors only, no robot commands."""
import os
import signal
import struct
import subprocess
import time

# Keep synthetic sensor streams separate from any lab ROS graph.
os.environ["ROS_DOMAIN_ID"] = "73"
os.environ["ROS_LOCALHOST_ONLY"] = "1"

import rclpy
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import Image, PointCloud2, PointField
from geometry_msgs.msg import TransformStamped
from tf2_msgs.msg import TFMessage

rclpy.init()
node = rclpy.create_node('mac_setup_offline_check')
camera = node.create_publisher(Image, '/camera/image_raw', qos_profile_sensor_data)
lidar = node.create_publisher(PointCloud2, '/point_cloud2', qos_profile_sensor_data)
tf = node.create_publisher(TFMessage, '/tf_static', QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
transform = TransformStamped()
transform.header.frame_id = 'odom'
transform.child_frame_id = 'base_link'
transform.transform.rotation.w = 1.0
transform.header.stamp = node.get_clock().now().to_msg()
tf.publish(TFMessage(transforms=[transform]))
log = open('/tmp/go2-rviz-smoke.log', 'w')
proc = subprocess.Popen(['mac-gui', 'rviz2', '-d', '/ros2_ws/src/docker/mac/rviz-sensors.rviz'],
                        stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
try:
    deadline = time.monotonic() + 18
    seen = set()
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError('RViz exited early: ' + str(proc.returncode))
        stamp = node.get_clock().now().to_msg()
        im = Image()
        im.header.frame_id = 'front_camera'
        im.header.stamp = stamp
        im.height, im.width, im.step, im.encoding = 48, 64, 192, 'bgr8'
        im.data = bytes([40, 180, 40]) * (48 * 64)
        camera.publish(im)
        cloud = PointCloud2()
        cloud.header.frame_id = 'odom'
        cloud.header.stamp = stamp
        cloud.height, cloud.width, cloud.point_step, cloud.row_step = 1, 25, 12, 300
        cloud.is_dense = True
        cloud.fields = [PointField(name=n, offset=i*4, datatype=PointField.FLOAT32, count=1)
                        for i, n in enumerate(['x', 'y', 'z'])]
        cloud.data = b''.join(struct.pack('<fff', x/4, y/4, 0.2) for x in range(5) for y in range(5))
        lidar.publish(cloud)
        rclpy.spin_once(node, timeout_sec=0.15)
        for topic in ['/camera/image_raw', '/point_cloud2']:
            endpoints = node.get_subscriptions_info_by_topic(topic)
            if any(e.node_name == 'rviz' and e.qos_profile.reliability == ReliabilityPolicy.BEST_EFFORT for e in endpoints):
                seen.add(topic)
    assert seen == {'/camera/image_raw', '/point_cloud2'}, seen
    print('PASS: RViz stayed running through XQuartz; both configured Best Effort subscriptions matched synthetic publishers.')
finally:
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGINT)
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=5)
    log.close()
    node.destroy_node()
    rclpy.shutdown()
    print(open('/tmp/go2-rviz-smoke.log').read()[-2500:])
