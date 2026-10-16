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
from std_srvs.srv import Trigger
from geometry_msgs.msg import PoseStamped

from builtin_interfaces.msg import Duration
from nav2_msgs.action import BackUp, NavigateToPose, Spin

import tf2_ros
from tf2_ros import TransformException

from go2_auto_mapper.obstacle_sensing import (
    angle_difference,
    free_distance_ahead,
    straight_line_clear,
)


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

        # Watching Nav2's local costmap while driving: if something sits
        # within obstacle_stop_distance of the nose for blocked_timeout
        # seconds, give up on that goal, back away, and head somewhere open.
        self.declare_parameter('obstacle_stop_distance', 0.3)
        self.declare_parameter('blocked_timeout', 2.0)
        self.declare_parameter('backup_distance', 0.3)

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

        self.obstacle_stop_distance = self.get_parameter(
            'obstacle_stop_distance'
        ).value
        self.blocked_timeout = self.get_parameter('blocked_timeout').value
        self.backup_distance = self.get_parameter('backup_distance').value

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

        # Nav2's local costmap (odom frame): the scan and 3D point cloud
        # merged, i.e. what the controller itself avoids.
        self.local_costmap = None
        self.local_costmap_sub = self.create_subscription(
            OccupancyGrid,
            '/local_costmap/costmap',
            self.local_costmap_callback,
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

        # Nav2's behavior server turns or backs the robot up, checking the
        # local costmap for collisions. One maneuver runs at a time.
        self.spin_client = ActionClient(self, Spin, '/spin')
        self.backup_client = ActionClient(self, BackUp, '/backup')
        self.scan_pending = self.get_parameter('scan_on_start').value
        self.backup_pending = False
        self.maneuver_name = None
        self.maneuver_active = False
        self.maneuver_handle = None
        self.maneuver_sent_time = None
        self.maneuver_time_allowance = 0.0

        # Set when a goal is abandoned for an obstacle ahead: the heading
        # (map frame) that was blocked and when, so the next goals avoid that
        # direction and favor longer walks into open space for a while.
        self.blocked_since = None
        self.blocked_heading = None
        self.blocked_time = None

        self.exploration_complete_logged = False

        # Don't start immediately.
        self.timer = self.create_timer(
            2.0,
            self.exploration_loop
        )

        # Faster than the exploration loop: at 0.5 m/s the robot covers
        # 1 m in 2 s, too far between looks at what's ahead.
        self.watch_timer = self.create_timer(
            WATCH_PERIOD_SEC,
            self.watch_ahead
        )

        # /frontier_explorer/scan: a 360 degree scan on request (the RViz
        # AutoMapper panel's Scan button, or `ros2 service call`).
        self.goal_cancelled_for_scan = False
        self.scan_service = self.create_service(
            Trigger, '~/scan', self.handle_scan_request
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

    def local_costmap_callback(self, msg):

        if msg.info.width and msg.info.height and msg.info.resolution > 0.0:
            self.local_costmap = msg

    # ==========================================================
    # GET ROBOT POSITION
    # ==========================================================

    def get_robot_pose(self, frame):
        """(x, y, yaw) of the robot in `frame`, or None if TF can't tell."""

        try:
            t = self.tf_buffer.lookup_transform(
                frame, self.robot_frame, rclpy.time.Time()
            ).transform
        except TransformException:
            return None

        q = t.rotation
        yaw = math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        )
        return t.translation.x, t.translation.y, yaw

    def local_view(self):
        """The local costmap plus the robot's pose in its frame, and the yaw
        to add to a map-frame heading to get a costmap-frame one. None until
        Nav2 publishes a costmap and TF has both poses."""

        if self.local_costmap is None:
            return None

        local_pose = self.get_robot_pose(self.local_costmap.header.frame_id)
        map_pose = self.get_robot_pose(self.map_frame)
        if local_pose is None or map_pose is None:
            return None

        x, y, yaw = local_pose
        return self.local_costmap, x, y, yaw, yaw - map_pose[2]

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

        # What Nav2 sees around the robot, for the straight-line and
        # blocked-direction checks below. Without it (no costmap yet), every
        # direction counts as open.
        view = self.local_view()
        blocked = self.recently_blocked() and self.blocked_heading is not None

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

            goal_range = math.hypot(goal_x - robot_x, goal_y - robot_y)
            bearing = math.atan2(goal_y - robot_y, goal_x - robot_x)

            if blocked:
                # Just turned away from an obstacle: take the longest walk
                # on offer, to get clear of that spot.
                score = -goal_range
            else:
                # Prefer nearby large frontiers.
                score = (
                    distance
                    -
                    0.02 * len(frontier)
                )

            is_far = goal_range >= self.min_goal_distance

            line_clear = True
            if view is not None:
                grid, local_x, local_y, _, map_to_local_yaw = view
                line_clear = straight_line_clear(
                    grid, local_x, local_y,
                    bearing + map_to_local_yaw,
                    min(goal_range, LINE_CHECK_M)
                )

            toward_blocked = blocked and (
                angle_difference(bearing, self.blocked_heading)
                < BLOCKED_CONE_RAD
            )

            candidates.append(
                (
                    score,
                    goal_x,
                    goal_y,
                    len(frontier),
                    is_far,
                    line_clear,
                    toward_blocked
                )
            )

        if not candidates:
            return None

        # In order: stay away from a just-blocked direction, then walk far
        # enough, then have a clear straight line in Nav2's costmap, then the
        # score. Each only breaks ties of the ones before it, so exploring
        # never stalls when no candidate is ideal.
        best = min(
            candidates,
            key=lambda c: (c[6], not c[4], not c[5], c[0])
        )

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

            elif self.goal_cancelled_for_scan:

                # Interrupted for a requested scan: not the goal's fault.
                self.get_logger().info('Goal paused for the requested scan.')

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
        self.goal_cancelled_for_scan = False

    # ==========================================================
    # SCAN ON REQUEST
    # ==========================================================

    def handle_scan_request(self, request, response):
        """Turn 360 degrees as soon as possible: the current goal is paused
        (not counted as failed), and failed spots are forgiven, since the
        scan gives SLAM fresh data and they may be reachable now."""

        if self.maneuver_active and self.maneuver_name == 'Scan':
            response.success = False
            response.message = 'Already scanning.'
            return response

        if self.goal_active and self.current_goal_handle is not None:
            self.goal_cancelled_for_scan = True
            self.current_goal_handle.cancel_goal_async()

        self.failed_goals = []
        self.blocked_time = None
        self.scan_pending = True

        self.get_logger().info('Scan requested.')
        response.success = True
        response.message = (
            'Scan queued: it starts once the current move stops.'
            if self.goal_active or self.maneuver_active
            else 'Scan starting.'
        )
        return response

    # ==========================================================
    # MANEUVERS: 360 DEGREE SCAN, BACKING AWAY
    # ==========================================================

    def start_scan(self):

        goal = Spin.Goal()
        goal.target_yaw = float(self.scan_yaw)
        goal.time_allowance = Duration(sec=int(self.scan_time_allowance))

        if self.start_maneuver(
            self.spin_client, goal, 'Scan', self.scan_time_allowance
        ):
            self.scan_pending = False
            self.get_logger().info('Turning in place to scan the surroundings.')

    def start_backup(self):

        goal = BackUp.Goal()
        goal.target.x = float(self.backup_distance)
        goal.speed = BACKUP_SPEED_MPS
        goal.time_allowance = Duration(sec=int(BACKUP_TIME_ALLOWANCE_SEC))

        # Clear the flag even if Nav2 isn't ready: backing away is a nicety,
        # and waiting for it would stall exploring.
        self.backup_pending = False
        if self.start_maneuver(
            self.backup_client, goal, 'Back-up', BACKUP_TIME_ALLOWANCE_SEC
        ):
            self.get_logger().info(
                f'Backing up {self.backup_distance:.1f} m from the obstacle.'
            )

    def start_maneuver(self, client, goal, name, time_allowance):
        """Send a Nav2 behavior goal; False if its server isn't up yet."""

        if not client.server_is_ready():
            self.get_logger().info(
                f'Waiting for Nav2 before: {name}...',
                throttle_duration_sec=5.0
            )
            return False

        self.maneuver_name = name
        self.maneuver_active = True
        self.maneuver_sent_time = time.monotonic()
        self.maneuver_time_allowance = time_allowance

        future = client.send_goal_async(goal)
        future.add_done_callback(self.maneuver_response_callback)
        return True

    def maneuver_response_callback(self, future):

        try:
            goal_handle = future.result()
        except Exception as e:
            self.get_logger().warn(f'{self.maneuver_name} failed to start: {e}')
            self.finish_maneuver()
            return

        if not goal_handle.accepted:
            self.get_logger().warn(
                f'Nav2 rejected the {self.maneuver_name}; skipping it.'
            )
            self.finish_maneuver()
            return

        self.maneuver_handle = goal_handle
        goal_handle.get_result_async().add_done_callback(
            self.maneuver_result_callback
        )

    def maneuver_result_callback(self, future):

        try:
            status = future.result().status
            if status == 4:
                self.get_logger().info(f'{self.maneuver_name} complete.')
            else:
                # A blocked turn or back-up (obstacle too close) shouldn't
                # stop exploring.
                self.get_logger().warn(
                    f'{self.maneuver_name} ended early with status {status}; '
                    'continuing.'
                )
        except Exception as e:
            self.get_logger().warn(f'{self.maneuver_name} result error: {e}')

        self.finish_maneuver()

    def finish_maneuver(self):

        self.maneuver_handle = None
        self.maneuver_active = False
        self.maneuver_sent_time = None

    # ==========================================================
    # OBSTACLE AHEAD
    # ==========================================================

    def watch_ahead(self):
        """While driving to a goal, give it up if an obstacle has been right
        in front of the nose for blocked_timeout seconds.

        Nav2 steers around obstacles it can, so a short look at a wall (e.g.
        while turning onto a path) is normal; staying nose-to-wall means the
        controller is stuck or about to push into it.
        """

        try:
            if not self.goal_active or self.current_goal_handle is None:
                self.blocked_since = None
                return

            view = self.local_view()
            if view is None:
                return
            grid, x, y, yaw, _ = view

            gap = free_distance_ahead(
                grid, x, y, yaw, self.obstacle_stop_distance
            )
            if gap is None:
                self.blocked_since = None
                return

            now = time.monotonic()
            if self.blocked_since is None:
                self.blocked_since = now
                return
            if now - self.blocked_since < self.blocked_timeout:
                return

            map_pose = self.get_robot_pose(self.map_frame)
            self.blocked_heading = map_pose[2] if map_pose else None
            self.blocked_time = now
            self.blocked_since = None

            self.get_logger().warn(
                f'Obstacle {gap:.2f} m ahead for {self.blocked_timeout:.1f} s; '
                'abandoning this goal and heading somewhere open.'
            )
            # The result callback then blacklists the goal and frees the loop.
            self.current_goal_handle.cancel_goal_async()
            self.backup_pending = True

        except Exception as e:
            # Same reason as exploration_loop: never let a callback error
            # crash the node while a goal is in flight.
            self.get_logger().error(f'Obstacle watch error: {e}')

    def recently_blocked(self):

        return (
            self.blocked_time is not None
            and time.monotonic() - self.blocked_time < BLOCKED_MEMORY_SEC
        )

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

        # Maneuvers only need odometry, not the map, so the startup scan runs
        # before SLAM has a map: turning in place is what gives it one.
        if self.maneuver_active:
            if (
                self.maneuver_sent_time is not None
                and time.monotonic() - self.maneuver_sent_time
                > self.maneuver_time_allowance + 10.0
            ):
                self.get_logger().warn(
                    f'No {self.maneuver_name} result, continuing without it.'
                )
                self.finish_maneuver()
            return

        if not self.goal_active:
            if self.backup_pending:
                self.start_backup()
                return
            if self.scan_pending:
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
            self.get_logger().info(
                'No usable goal: every frontier is too close to a wall or '
                'failed recently. Waiting for the map to change or for '
                f'failed spots to expire ({self.failed_goal_cooldown_sec:.0f} s).',
                throttle_duration_sec=10.0
            )
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
        if self.maneuver_handle is not None:
            self.get_logger().info(f'Cancelling the {self.maneuver_name}.')
            future = self.maneuver_handle.cancel_goal_async()
            rclpy.spin_until_future_complete(self, future, timeout_sec=2.0)


PR_SET_PDEATHSIG = 1  # from <linux/prctl.h>

# Spacing of the extra goal candidates taken along a long frontier.
FRONTIER_SAMPLE_SPACING_M = 1.0

# How often watch_ahead looks at the local costmap while driving.
WATCH_PERIOD_SEC = 0.25

# After a goal is abandoned for an obstacle ahead: how long to steer goal
# choice away from that heading, and how wide a cone around it to avoid.
BLOCKED_MEMORY_SEC = 30.0
BLOCKED_CONE_RAD = math.radians(45.0)

# How far toward a goal to check the straight line in the local costmap;
# beyond this the costmap (20 x 20 m) has little to say anyway.
LINE_CHECK_M = 3.0

# Backing away from an obstacle: slow, and with a short time limit.
BACKUP_SPEED_MPS = 0.15
BACKUP_TIME_ALLOWANCE_SEC = 10.0

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
