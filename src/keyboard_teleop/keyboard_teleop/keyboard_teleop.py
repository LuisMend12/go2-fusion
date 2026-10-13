import select
import sys
import termios
import threading
import time
import tty

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from geometry_msgs.msg import Twist


# key -> (linear.x sign, linear.y sign, angular.z sign)
MOVE_BINDINGS = {
    'w': (1, 0, 0),
    's': (-1, 0, 0),
    'a': (0, 0, 1),
    'd': (0, 0, -1),
    'q': (0, 1, 0),
    'e': (0, -1, 0),
}

LINEAR_SPEED_DEFAULT = 0.5
ANGULAR_SPEED_DEFAULT = 1.5
LINEAR_SPEED_MIN, LINEAR_SPEED_MAX = 0.1, 1.0
ANGULAR_SPEED_MIN, ANGULAR_SPEED_MAX = 0.3, 2.5
LINEAR_SPEED_STEP = 0.1
ANGULAR_SPEED_STEP = 0.3

# How long an axis keeps moving after its key was last seen, before the
# watchdog zeroes just that axis. Lets you curve (hold W, tap D to turn,
# stop tapping D to go straight again) while still auto-stopping if you
# walk away or the terminal loses focus.
AXIS_HOLD_TIMEOUT = 0.4
PUBLISH_RATE_HZ = 10.0


class KeyboardTeleop(Node):

    def __init__(self):
        super().__init__('keyboard_teleop')

        self.publisher = self.create_publisher(Twist, '/cmd_vel_keyboard', 10)

        self.running = True
        self.lock = threading.Lock()

        self.linear_speed = LINEAR_SPEED_DEFAULT
        self.angular_speed = ANGULAR_SPEED_DEFAULT

        self.linear_x = 0.0
        self.linear_y = 0.0
        self.angular_z = 0.0
        self._was_moving = False
        self.last_linear_x_time = 0.0
        self.last_linear_y_time = 0.0
        self.last_angular_z_time = 0.0

        # Publishes continuously at a fixed rate (rather than once per
        # keystroke) so held keys produce smooth motion regardless of the
        # terminal's OS key-repeat rate, and so twist_mux's own 0.5s
        # per-topic timeout doesn't drop us between repeats.
        self.create_timer(1.0 / PUBLISH_RATE_HZ, self._on_timer)

        self._print_help()

    def _print_help(self):
        self.get_logger().info('Keyboard teleoperation started.')
        self.get_logger().info('W/S = forward/backward')
        self.get_logger().info('A/D = turn left/right')
        self.get_logger().info('Q/E = strafe left/right')
        self.get_logger().info('Hold multiple keys in sequence to combine, e.g. W then D to curve')
        self.get_logger().info('Z/X = decrease/increase speed')
        self.get_logger().info('SPACE = stop, ESC = quit')
        self._log_speed()

    def _log_speed(self):
        self.get_logger().info(
            f'Speed: linear={self.linear_speed:.2f} m/s, '
            f'angular={self.angular_speed:.2f} rad/s'
        )

    def handle_key(self, key):
        now = time.monotonic()

        with self.lock:
            if key in MOVE_BINDINGS:
                lx, ly, az = MOVE_BINDINGS[key]

                if lx:
                    self.linear_x = lx * self.linear_speed
                    self.last_linear_x_time = now
                if ly:
                    self.linear_y = ly * self.linear_speed
                    self.last_linear_y_time = now
                if az:
                    self.angular_z = az * self.angular_speed
                    self.last_angular_z_time = now

            elif key == ' ':
                self.linear_x = 0.0
                self.linear_y = 0.0
                self.angular_z = 0.0

            elif key == 'z':
                self.linear_speed = max(
                    LINEAR_SPEED_MIN, self.linear_speed - LINEAR_SPEED_STEP
                )
                self.angular_speed = max(
                    ANGULAR_SPEED_MIN, self.angular_speed - ANGULAR_SPEED_STEP
                )
                self._log_speed()

            elif key == 'x':
                self.linear_speed = min(
                    LINEAR_SPEED_MAX, self.linear_speed + LINEAR_SPEED_STEP
                )
                self.angular_speed = min(
                    ANGULAR_SPEED_MAX, self.angular_speed + ANGULAR_SPEED_STEP
                )
                self._log_speed()

    def _on_timer(self):
        now = time.monotonic()

        with self.lock:
            if self.linear_x and now - self.last_linear_x_time > AXIS_HOLD_TIMEOUT:
                self.linear_x = 0.0
            if self.linear_y and now - self.last_linear_y_time > AXIS_HOLD_TIMEOUT:
                self.linear_y = 0.0
            if self.angular_z and now - self.last_angular_z_time > AXIS_HOLD_TIMEOUT:
                self.angular_z = 0.0

            moving = bool(self.linear_x or self.linear_y or self.angular_z)
            # Publish only while moving, plus one stop when motion ends. An
            # idle stream of zeros on /cmd_vel_keyboard (twist_mux priority 9)
            # would hold the keyboard lane active and block Nav2, the agent
            # and object navigation.
            if not moving and not self._was_moving:
                return
            self._was_moving = moving

            msg = Twist()
            msg.linear.x = self.linear_x
            msg.linear.y = self.linear_y
            msg.angular.z = self.angular_z

        self.publisher.publish(msg)

    def publish_stop(self):
        if not rclpy.ok():
            return
        with self.lock:
            # Zero the shared state too, not just this one publish, so a
            # _on_timer tick that sneaks in between this call and the node
            # actually shutting down still re-publishes zero instead of
            # replaying the last held velocity.
            self.linear_x = 0.0
            self.linear_y = 0.0
            self.angular_z = 0.0
            try:
                self.publisher.publish(Twist())
            except Exception as exc:
                self.get_logger().warn(f'Failed to publish stop command: {exc}')


def keyboard_thread(node):
    if not sys.stdin.isatty():
        node.get_logger().error(
            'stdin is not a terminal (run with "docker exec -it ..."); '
            'keyboard input will not work.'
        )
        node.running = False
        return

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    try:
        tty.setcbreak(fd)

        while node.running:
            # Poll with a timeout instead of blocking on read(), so this
            # thread notices node.running going False (e.g. Ctrl+C in the
            # main thread) within 0.2s instead of waiting on a keypress
            # that may never come. A blocking read() here would otherwise
            # leave the terminal stuck in cbreak mode, since this is a
            # daemon thread that gets killed without running `finally`
            # if the process exits while it's still blocked.
            ready, _, _ = select.select([sys.stdin], [], [], 0.2)
            if not ready:
                continue

            key = sys.stdin.read(1)

            if key == '':
                # EOF: stdin closed/disconnected.
                node.get_logger().info('stdin closed, quitting.')
                node.running = False
                break

            # ESC key
            if key == '\x1b':
                node.get_logger().info('Quitting.')
                node.running = False
                break

            node.handle_key(key.lower())

    finally:
        # Always leave the robot stopped, however this thread exits
        # (Esc, EOF, or node.running flipped False by the main thread).
        node.publish_stop()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    if rclpy.ok():
        rclpy.shutdown()


def main(args=None):
    rclpy.init(args=args)

    node = KeyboardTeleop()

    thread = threading.Thread(
        target=keyboard_thread,
        args=(node,),
        daemon=True
    )

    thread.start()

    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        # ExternalShutdownException fires here because keyboard_thread
        # calls rclpy.shutdown() from a different thread (on Esc/EOF)
        # while spin() is still running on this one.
        pass

    node.running = False
    thread.join(timeout=1.0)

    if rclpy.ok():
        rclpy.shutdown()

    node.destroy_node()


if __name__ == '__main__':
    main()
