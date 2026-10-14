import math

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState


class FrontLegController(Node):

    FRONT_JOINTS = [
        "FL_hip_joint",
        "FL_thigh_joint",
        "FL_calf_joint",
        "FR_hip_joint",
        "FR_thigh_joint",
        "FR_calf_joint",
    ]

    def __init__(self):
        super().__init__("front_leg_controller")

        self.joint_positions = {}

        self.subscription = self.create_subscription(
            JointState,
            "/joint_states",
            self.joint_state_callback,
            10,
        )

        # Current movement state
        self.active = False
        self.phase = 0.0

        # How fast the simulated motion progresses.
        # This is NOT a motor speed.
        self.phase_speed = 0.03

        self.timer = self.create_timer(
            0.02,       # 50 Hz
            self.control_loop
        )

        self.get_logger().info(
            "Front leg controller started in DRY-RUN mode."
        )

    def joint_state_callback(self, msg):

        for name, position in zip(msg.name, msg.position):
            if name in self.FRONT_JOINTS:
                self.joint_positions[name] = position

    def control_loop(self):

        # We need all six front-leg joints before doing anything.
        if not all(
            joint in self.joint_positions
            for joint in self.FRONT_JOINTS
        ):
            return

        if not self.active:
            return

        self.phase += self.phase_speed

        # Smooth oscillation between -1 and +1.
        motion = math.sin(self.phase)

        self.generate_command(motion)

    def generate_command(self, motion):

        # IMPORTANT:
        #
        # These are intentionally placeholders.
        # We are NOT assuming these are safe Go2 joint angles.
        #
        # Once the robot is available, we'll determine the
        # actual sitting position and safe movement range.

        amplitude = 0.0

        commands = {}

        for joint in self.FRONT_JOINTS:

            current = self.joint_positions[joint]

            target = current + amplitude * motion

            commands[joint] = target

        self.get_logger().info(
            f"DRY RUN | motion={motion:.3f} | "
            f"targets={commands}"
        )


def main(args=None):

    rclpy.init(args=args)

    node = FrontLegController()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
