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

    # Send the command once
    node.sit()

    # Keep the node alive briefly so ROS can actually transmit it
    node.create_timer(1.0, lambda: rclpy.shutdown())

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass

    node.destroy_node()

    if rclpy.ok():
        rclpy.shutdown()


if __name__ == "__main__":
    main()
