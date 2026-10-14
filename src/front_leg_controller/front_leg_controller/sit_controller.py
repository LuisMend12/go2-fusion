import rclpy
from rclpy.node import Node
from go2_interfaces.msg import WebRtcReq


class SitController(Node):

    def __init__(self):
        super().__init__("sit_controller")

        self.publisher = self.create_publisher(
            WebRtcReq,
            "/webrtc_req",
            10
        )

        self.get_logger().info("Sit controller ready.")

    def sit(self):
        msg = WebRtcReq()

        # Unitree Go2 Sport API
        # 1009 = Sit
        msg.api_id = 1009

        # Sit command takes an empty JSON object
        msg.parameter = "{}"

        # Unitree Sport API topic
        msg.topic = "rt/api/sport/request"

        # 0 = let the SDK assign the ID
        msg.id = 0

        # Normal priority
        msg.priority = 0

        self.publisher.publish(msg)

        self.get_logger().info("Sent SIT command (API 1009).")


def main(args=None):
    rclpy.init(args=args)

    node = SitController()

    # ROS2 pub/sub gives no delivery guarantee to a not-yet-connected
    # subscriber, so publishing immediately and just hoping a fixed 1s
    # wait was enough risked silently dropping the command if the
    # driver's /webrtc_req bridge wasn't up yet. Wait for an actual
    # subscriber instead, capped by a timeout so this doesn't hang
    # forever if the driver is down.
    timeout_sec = 5.0
    wait_start = node.get_clock().now()
    while (
        node.publisher.get_subscription_count() == 0
        and (node.get_clock().now() - wait_start).nanoseconds / 1e9 < timeout_sec
    ):
        rclpy.spin_once(node, timeout_sec=0.1)

    if node.publisher.get_subscription_count() == 0:
        node.get_logger().warn(
            f"No subscriber on /webrtc_req after waiting {timeout_sec:.0f}s; "
            "sending SIT anyway, but it will likely be dropped."
        )

    # Send the command once
    node.sit()

    # Give the message a brief moment to actually go out before exiting.
    rclpy.spin_once(node, timeout_sec=0.5)

    node.destroy_node()

    if rclpy.ok():
        rclpy.shutdown()


if __name__ == "__main__":
    main()
