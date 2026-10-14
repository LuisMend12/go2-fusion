#!/usr/bin/env python3

import ctypes
import math
import signal
import time
from collections import deque

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from nav_msgs.msg import OccupancyGrid
from geometry_msgs.msg import PoseStamped

from builtin_interfaces.msg import Duration
from nav2_msgs.action import NavigateToPose, Spin

import tf2_ros
from tf2_ros import TransformException


class FrontierExplorer(Node):

    def __init__(self):
        super().__init__('frontier_explorer')

        # -----------------------------
        # Parameters
        # -----------------------------

        self.declare_parameter('map_topic', '/map')
        self.declare_parameter('robot_frame', 'base_link')
        self.declare_parameter('map_frame', 'map')

        self.declare_parameter('min_frontier_size', 5)
        self.declare_parameter('goal_distance', 0.8)
        # Frontiers closer than this are only used once no farther one is
        # left, so each leg covers new ground instead of shuffling in place.
        self.declare_parameter('min_goal_distance', 1.5)
        # Goals closer than this to a wall in the SLAM map are skipped:
        # Nav2 can't place the robot's body there, and it scrapes walls.
        self.declare_parameter('wall_clearance', 0.5)

        # A full turn in place gives SLAM a 360 degree lidar view, so it can
        # place the robot on the map before (and after) each leg of exploring.
        self.declare_parameter('scan_on_start', True)
        self.declare_parameter('scan_after_goal', True)
        self.declare_parameter('scan_yaw', 2.0 * math.pi)
        self.declare_parameter('scan_time_allowance', 30.0)

        self.map_topic = self.get_parameter(
            'map_topic'
        ).value

        self.robot_frame = self.get_parameter(
            'robot_frame'
        ).value

        self.map_frame = self.get_parameter(
            'map_frame'
        ).value

        self.min_frontier_size = self.get_parameter(
            'min_frontier_size'
        ).value

        self.goal_distance = self.get_parameter(
            'goal_distance'
        ).value

        self.min_goal_distance = self.get_parameter('min_goal_distance').value
        self.wall_clearance = self.get_parameter('wall_clearance').value

        self.scan_after_goal = self.get_parameter('scan_after_goal').value
        self.scan_yaw = self.get_parameter('scan_yaw').value
        self.scan_time_allowance = self.get_parameter(
            'scan_time_allowance'
        ).value

        # -----------------------------
        # Map
        # -----------------------------

        self.map = None

        # /map is latched. A volatile subscription misses the grid that was
        # published before this node started.
        map_qos = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
        )

        self.map_sub = self.create_subscription(
            OccupancyGrid,
            self.map_topic,
            self.map_callback,
            map_qos
        )

        # -----------------------------
        # TF
        # -----------------------------

        self.tf_buffer = tf2_ros.Buffer(
            cache_time=rclpy.duration.Duration(seconds=10)
        )

        self.tf_listener = tf2_ros.TransformListener(
            self.tf_buffer,
            self
        )

        # -----------------------------
        # Nav2
        # -----------------------------

        self.nav_client = ActionClient(
            self,
            NavigateToPose,
            '/navigate_to_pose'
        )

        self.current_goal = None
        self.goal_active = False
        self.current_goal_handle = None
        self.goal_sent_time = None

        # (x, y) -> time.monotonic() of goals Nav2 rejected or failed,
        # so we don't immediately re-select the same bad spot forever.
        self.failed_goals = []
        # Longer than a few failed attempts (~25 s each), or the same handful
        # of nearby spots just rotate through the list.
        self.failed_goal_cooldown_sec = 120.0
        self.failed_goal_radius = 0.5

        # If Nav2 accepts a goal but then never reports a result (e.g. the
        # action server drops the connection after accepting), neither
        # done-callback fires and goal_active would stay True forever,
        # silently halting exploration. This bounds how long we'll wait.
        self.goal_timeout_sec = 60.0

        # Nav2's behavior server turns the robot in place, checking the
        # local costmap for collisions.
        self.spin_client = ActionClient(self, Spin, '/spin')
        self.scan_pending = self.get_parameter('scan_on_start').value
        self.scan_active = False
        self.scan_handle = None
        self.scan_sent_time = None

        self.exploration_complete_logged = False

        # Don't start immediately.
        self.timer = self.create_timer(
            2.0,
            self.exploration_loop
        )

        self.get_logger().info(
            'Go2 Frontier Explorer started.'
        )

    # ==========================================================
    # MAP CALLBACK
    # ==========================================================

    def map_callback(self, msg):

        expected = msg.info.width * msg.info.height
        if (
            msg.info.width == 0
            or msg.info.height == 0
            or msg.info.resolution <= 0.0
            or len(msg.data) < expected
        ):
            self.get_logger().warn(
                f'Ignoring occupancy grid: {msg.info.width}x{msg.info.height}, '
                f'resolution={msg.info.resolution}, {len(msg.data)} cells',
                throttle_duration_sec=5.0
            )
            return

        self.map = msg

    # ==========================================================
    # GET ROBOT POSITION
    # ==========================================================

    def get_robot_position(self):

        try:

            transform = self.tf_buffer.lookup_transform(
                self.map_frame,
                self.robot_frame,
                rclpy.time.Time()
            )

            x = transform.transform.translation.x
            y = transform.transform.translation.y

            return x, y

        except TransformException:

            return None

    # ==========================================================
    # MAP CELL HELPERS
    # ==========================================================

    def index(self, x, y):

        return y * self.map.info.width + x

    def valid_cell(self, x, y):

        return (
            0 <= x < self.map.info.width
            and
            0 <= y < self.map.info.height
        )

    def cell_value(self, x, y):

        return self.map.data[
            self.index(x, y)
        ]

    # ==========================================================
    # FRONTIER DETECTION
    # ==========================================================

    def is_frontier(self, x, y):

        if not self.valid_cell(x, y):
            return False

        # Frontier cells themselves should be FREE.
        if self.cell_value(x, y) != 0:
            return False

        neighbors = [
            (x + 1, y),
            (x - 1, y),
            (x, y + 1),
            (x, y - 1)
        ]

        for nx, ny in neighbors:

            if not self.valid_cell(nx, ny):
                continue

            # Unknown neighboring cell
            if self.cell_value(nx, ny) == -1:
                return True

        return False

    # ==========================================================
    # FIND FRONTIER GROUPS
    # ==========================================================

    def find_frontiers(self):

        frontiers = []

        visited = set()

        width = self.map.info.width
        height = self.map.info.height

        for y in range(height):

            for x in range(width):

                if (x, y) in visited:
                    continue

                if not self.is_frontier(x, y):
                    continue

                # BFS frontier clustering
                queue = deque([(x, y)])
                visited.add((x, y))

                cluster = []

                while queue:

                    cx, cy = queue.popleft()

                    cluster.append((cx, cy))

                    neighbors = [
                        (cx + 1, cy),
                        (cx - 1, cy),
                        (cx, cy + 1),
                        (cx, cy - 1)
                    ]

                    for nx, ny in neighbors:

                        if not self.valid_cell(nx, ny):
                            continue

                        if (nx, ny) in visited:
                            continue

                        if self.is_frontier(nx, ny):

                            visited.add((nx, ny))
                            queue.append((nx, ny))

                if len(cluster) >= self.min_frontier_size:

                    frontiers.append(cluster)

        return frontiers

    # ==========================================================
    # FRONTIER CENTER
    # ==========================================================

    def frontier_center(self, frontier):

        mean_x = sum(p[0] for p in frontier) / len(frontier)
        mean_y = sum(p[1] for p in frontier) / len(frontier)

        # The frontier cell nearest the mean, not the mean itself: a frontier
        # that wraps around the robot (common right after the startup scan)
        # has its mean on the robot, which made every goal a short hop.
        return min(
            frontier,
            key=lambda p: (p[0] - mean_x) ** 2 + (p[1] - mean_y) ** 2
        )

    def frontier_targets(self, frontier):
        """Points to aim at on one frontier: its center, plus a cell about
        every FRONTIER_SAMPLE_SPACING_M for long frontiers. A long frontier
        (e.g. the whole edge of a room) then offers its far parts too, not
        just the part nearest its middle."""

        step = max(
            1,
            int(FRONTIER_SAMPLE_SPACING_M / self.map.info.resolution)
        )

        return [self.frontier_center(frontier)] + frontier[::step]

    # ==========================================================
    # GRID → WORLD
    # ==========================================================

    def world_to_grid(self, wx, wy):

        resolution = self.map.info.resolution

        origin_x = self.map.info.origin.position.x
        origin_y = self.map.info.origin.position.y

        gx = (wx - origin_x) / resolution
        gy = (wy - origin_y) / resolution

        return gx, gy

    def grid_to_world(self, gx, gy):

        resolution = self.map.info.resolution

        origin_x = self.map.info.origin.position.x
        origin_y = self.map.info.origin.position.y

        wx = origin_x + (gx + 0.5) * resolution
        wy = origin_y + (gy + 0.5) * resolution

        return wx, wy

    # ==========================================================
    # PICK FRONTIER
    # ==========================================================

    def near_obstacle(self, gx, gy):
        """True if an occupied map cell is within wall_clearance of (gx, gy)."""

        radius = int(math.ceil(self.wall_clearance / self.map.info.resolution))

        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx * dx + dy * dy > radius * radius:
                    continue
                x, y = gx + dx, gy + dy
                if (
                    self.valid_cell(x, y)
                    and self.cell_value(x, y) >= OCCUPIED_THRESHOLD
                ):
                    return True

        return False

    def is_goal_blacklisted(self, x, y):
        now = time.monotonic()

        # Drop expired entries so this list doesn't grow unbounded over
        # a long exploration run.
        self.failed_goals = [
            (fx, fy, t) for fx, fy, t in self.failed_goals
            if now - t < self.failed_goal_cooldown_sec
        ]

        for fx, fy, _ in self.failed_goals:
            if math.hypot(x - fx, y - fy) < self.failed_goal_radius:
                return True

        return False

    def choose_frontier(self, frontiers, robot_x, robot_y):

        candidates = []

        targets = [
            (frontier, point)
            for frontier in frontiers
            for point in self.frontier_targets(frontier)
        ]

        for frontier, (gx, gy) in targets:

            # Convert frontier center to world coordinates.
            frontier_x, frontier_y = self.grid_to_world(gx, gy)

            distance = math.sqrt(
                (frontier_x - robot_x) ** 2
                +
                (frontier_y - robot_y) ** 2
            )

            # Don't choose something extremely close to the robot.
            # Checked before the neighbor search below so we don't pay
            # for an 17x17-cell scan on a candidate we'll discard anyway.
            if distance < 0.5:
                continue

            # Stop short of the unknown boundary. A goal on the frontier
            # cell itself is rejected by Nav2. goal_distance is how far
            # back toward the robot that goal should sit.
            pull = min(float(self.goal_distance), max(0.0, distance - 0.5))
            if distance > 1e-6:
                target_x = frontier_x + (robot_x - frontier_x) * (pull / distance)
                target_y = frontier_y + (robot_y - frontier_y) * (pull / distance)
            else:
                target_x, target_y = frontier_x, frontier_y

            target_gx, target_gy = self.world_to_grid(target_x, target_y)

            search_radius = 8

            center_x = int(math.floor(target_gx))
            center_y = int(math.floor(target_gy))

            free_cells = []

            for dy in range(-search_radius, search_radius + 1):

                for dx in range(-search_radius, search_radius + 1):

                    x = center_x + dx
                    y = center_y + dy

                    if not self.valid_cell(x, y):
                        continue

                    # Goal must be known free space.
                    if self.cell_value(x, y) != 0:
                        continue

                    wx, wy = self.grid_to_world(x, y)

                    d = math.hypot(wx - target_x, wy - target_y)

                    free_cells.append((d, x, y, wx, wy))

            # Closest free cell that isn't against a wall. Checking clearance
            # only until the first hit keeps this cheap.
            free_cells.sort()
            best_goal = next(
                (
                    (wx, wy) for _, x, y, wx, wy in free_cells
                    if not self.near_obstacle(x, y)
                ),
                None
            )

            if best_goal is None:
                continue

            goal_x, goal_y = best_goal

            # Skip spots Nav2 recently rejected or failed to reach, so a
            # single bad frontier (e.g. too close to an obstacle) doesn't
            # get re-selected and retried forever.
            if self.is_goal_blacklisted(goal_x, goal_y):
                continue

            # Prefer nearby large frontiers.
            score = (
                distance
                -
                0.02 * len(frontier)
            )

            is_far = (
                math.hypot(goal_x - robot_x, goal_y - robot_y)
                >= self.min_goal_distance
            )

            candidates.append(
                (
                    score,
                    goal_x,
                    goal_y,
                    len(frontier),
                    is_far
                )
            )

        if not candidates:
            return None

        far = [c for c in candidates if c[4]]
        pool = far if far else candidates

        best = min(pool, key=lambda c: c[0])

        return best[:4]

    # ==========================================================
    # SEND NAVIGATION GOAL
    # ==========================================================

    def send_goal(self, x, y):

        if not self.nav_client.server_is_ready():
            self.get_logger().warn(
                'Waiting for Nav2...'
            )
            return

        goal = NavigateToPose.Goal()

        goal.pose = PoseStamped()

        goal.pose.header.frame_id = self.map_frame
        goal.pose.header.stamp = self.get_clock().now().to_msg()

        goal.pose.pose.position.x = x
        goal.pose.pose.position.y = y

        # Keep robot orientation unchanged.
        goal.pose.pose.orientation.w = 1.0

        self.get_logger().info(
            f'Sending exploration goal: '
            f'x={x:.2f}, y={y:.2f}'
        )

        self.goal_active = True
        self.current_goal = (x, y)
        self.goal_sent_time = time.monotonic()

        future = self.nav_client.send_goal_async(
            goal
        )

        future.add_done_callback(
            self.goal_response_callback
        )

    # ==========================================================
    # NAV2 RESPONSE
    # ==========================================================

    def goal_response_callback(self, future):

        try:

            goal_handle = future.result()

        except Exception as e:

            self.get_logger().error(
                f'Navigation goal failed: {e}'
            )

            self.blacklist_current_goal()
            self.goal_active = False
            self.goal_sent_time = None
            return

        if not goal_handle.accepted:

            self.get_logger().warn(
                'Nav2 rejected the exploration goal.'
            )

            self.blacklist_current_goal()
            self.goal_active = False
            self.goal_sent_time = None
            return

        self.current_goal_handle = goal_handle

        self.get_logger().info(
            'Exploration goal accepted.'
        )

        result_future = goal_handle.get_result_async()

        result_future.add_done_callback(
            self.navigation_result_callback
        )

    def blacklist_current_goal(self):
        if self.current_goal is not None:
            x, y = self.current_goal
            self.failed_goals.append((x, y, time.monotonic()))

    # ==========================================================
    # NAVIGATION RESULT
    # ==========================================================

    def navigation_result_callback(self, future):

        try:

            result = future.result()

            status = result.status

            if status == 4:

                self.get_logger().info(
                    'Reached exploration goal.'
                )

                if self.scan_after_goal:
                    self.scan_pending = True

            else:

                self.get_logger().warn(
                    f'Navigation ended with status {status}'
                )

                self.blacklist_current_goal()

        except Exception as e:

            self.get_logger().error(
                f'Navigation result error: {e}'
            )

            self.blacklist_current_goal()

        self.current_goal_handle = None
        self.goal_active = False
        self.goal_sent_time = None

    # ==========================================================
    # 360 DEGREE SCAN
    # ==========================================================

    def start_scan(self):

        if not self.spin_client.server_is_ready():
            self.get_logger().info(
                'Waiting for Nav2 spin behavior before the scan...',
                throttle_duration_sec=5.0
            )
            return

        goal = Spin.Goal()
        goal.target_yaw = float(self.scan_yaw)
        goal.time_allowance = Duration(sec=int(self.scan_time_allowance))

        self.get_logger().info('Turning in place to scan the surroundings.')

        self.scan_pending = False
        self.scan_active = True
        self.scan_sent_time = time.monotonic()

        future = self.spin_client.send_goal_async(goal)
        future.add_done_callback(self.scan_response_callback)

    def scan_response_callback(self, future):

        try:
            goal_handle = future.result()
        except Exception as e:
            self.get_logger().warn(f'Scan failed to start: {e}')
            self.finish_scan()
            return

        if not goal_handle.accepted:
            self.get_logger().warn('Nav2 rejected the scan; skipping it.')
            self.finish_scan()
            return

        self.scan_handle = goal_handle
        goal_handle.get_result_async().add_done_callback(
            self.scan_result_callback
        )

    def scan_result_callback(self, future):

        try:
            status = future.result().status
            if status == 4:
                self.get_logger().info('Scan complete.')
            else:
                # A blocked turn (obstacle too close) shouldn't stop
                # exploring: the map is just updated from fewer angles.
                self.get_logger().warn(
                    f'Scan ended early with status {status}; continuing.'
                )
        except Exception as e:
            self.get_logger().warn(f'Scan result error: {e}')

        self.finish_scan()

    def finish_scan(self):

        self.scan_handle = None
        self.scan_active = False
        self.scan_sent_time = None

    # ==========================================================
    # EXPLORATION LOOP
    # ==========================================================

    def exploration_loop(self):
        try:
            self._exploration_loop_impl()
        except Exception as e:
            # A callback exception here would otherwise propagate out of
            # rclpy.spin(), crashing the node before stop() gets a chance
            # to cancel any in-flight Nav2 goal — the robot would then
            # keep walking toward the last frontier with nothing watching
            # it. Log and skip this cycle instead; the next timer tick
            # tries again.
            self.get_logger().error(f'Exploration loop error: {e}')

    def _exploration_loop_impl(self):

        # The scan only needs odometry, not the map, so the startup scan runs
        # before SLAM has a map: turning in place is what gives it one.
        if self.scan_active:
            if (
                self.scan_sent_time is not None
                and time.monotonic() - self.scan_sent_time
                > self.scan_time_allowance + 10.0
            ):
                self.get_logger().warn('No scan result, continuing without it.')
                self.finish_scan()
            return

        if self.scan_pending and not self.goal_active:
            self.start_scan()
            return

        # Don't do anything until SLAM has produced a map.
        if self.map is None:
            self.get_logger().info(
                'Waiting for map...',
                throttle_duration_sec=5.0
            )
            return

        # If a goal was accepted but Nav2 never reported a result (e.g. the
        # action server dropped the connection post-acceptance), neither
        # done-callback will ever fire. Force a reset so exploration doesn't
        # stall forever.
        if (
            self.goal_active
            and self.goal_sent_time is not None
            and time.monotonic() - self.goal_sent_time > self.goal_timeout_sec
        ):
            self.get_logger().warn(
                'No Nav2 result after '
                f'{self.goal_timeout_sec:.0f}s, treating goal as stalled.'
            )
            self.blacklist_current_goal()
            self.current_goal_handle = None
            self.goal_active = False
            self.goal_sent_time = None

        # Don't issue multiple goals simultaneously.
        if self.goal_active:
            return

        robot_position = self.get_robot_position()

        if robot_position is None:

            # Normal for a few seconds at startup: SLAM only publishes the
            # map frame once it has matched enough scans.
            self.get_logger().info(
                f'Waiting for robot position '
                f'({self.map_frame} -> {self.robot_frame} from SLAM)...',
                throttle_duration_sec=5.0
            )

            return

        robot_x, robot_y = robot_position

        frontiers = self.find_frontiers()

        if not frontiers:

            if not self.exploration_complete_logged:
                self.get_logger().info(
                    'No frontiers found. Exploration complete.'
                )
                self.exploration_complete_logged = True

            return

        self.exploration_complete_logged = False

        self.get_logger().info(
            f'Found {len(frontiers)} frontier regions.'
        )

        selected = self.choose_frontier(
            frontiers,
            robot_x,
            robot_y
        )

        if selected is None:
            return

        score, x, y, size = selected

        self.get_logger().info(
            f'Selected frontier: '
            f'x={x:.2f}, '
            f'y={y:.2f}, '
            f'size={size}'
        )

        self.send_goal(x, y)

    def stop(self):
        # Cancel whatever Nav2 goal is in flight so the robot doesn't
        # keep walking toward it after we've stopped sending new ones.
        # rclpy.spin() has already returned by the time this runs, so we
        # spin briefly here too, otherwise the cancel request is just
        # queued and never actually sent before the node is destroyed.
        if self.current_goal_handle is not None:
            self.get_logger().info('Cancelling active navigation goal.')
            future = self.current_goal_handle.cancel_goal_async()
            rclpy.spin_until_future_complete(self, future, timeout_sec=2.0)
        if self.scan_handle is not None:
            self.get_logger().info('Cancelling the scan.')
            future = self.scan_handle.cancel_goal_async()
            rclpy.spin_until_future_complete(self, future, timeout_sec=2.0)


PR_SET_PDEATHSIG = 1  # from <linux/prctl.h>

# Spacing of the extra goal candidates taken along a long frontier.
FRONTIER_SAMPLE_SPACING_M = 1.0

# Occupancy grid value (0-100) at or above which a cell counts as a wall,
# matching map_server's default occupied threshold of 0.65.
OCCUPIED_THRESHOLD = 65


def stop_when_parent_dies():
    """Get SIGINT when the launching process exits, so the explorer shuts
    down cleanly (cancelling its Nav2 goal) instead of living on as an orphan.

    The RViz AutoMapper panel starts the explorer and stops it on Stop, but if
    RViz crashes or is killed, nothing stops it, and each orphan keeps sending
    Nav2 goals that fight the others.
    """
    try:
        libc = ctypes.CDLL('libc.so.6', use_errno=True)
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGINT)
    except OSError:
        pass  # Not Linux: run without the safeguard.


def main(args=None):

    stop_when_parent_dies()

    rclpy.init(args=args)

    node = FrontierExplorer()

    try:

        rclpy.spin(node)

    except (KeyboardInterrupt, ExternalShutdownException):
        pass

    node.stop()
    node.destroy_node()

    if rclpy.ok():
        rclpy.shutdown()


if __name__ == '__main__':
    main()
