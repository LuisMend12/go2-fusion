"""Conservative, ROS-independent checks for short holonomic escape moves."""

import math

from go2_auto_mapper.obstacle_sensing import cost_at


def scan_covers_move(scan, dx, dy):
    """Require measured free range throughout the swept padded body.

    Caller must supply a fresh scan expressed at base_link. Missing rays,
    NaNs and infinite returns do not prove clearance.
    """
    if scan.angle_increment <= 0:
        return False
    for ix in range(math.floor((-0.50 + min(0, dx)) / .025),
                    math.ceil((0.41 + max(0, dx)) / .025) + 1):
        for iy in range(math.floor((-0.25 + min(0, dy)) / .025),
                        math.ceil((0.25 + max(0, dy)) / .025) + 1):
            x, y = ix * .025, iy * .025
            radius = math.hypot(x, y)
            if radius < scan.range_min:
                continue
            angle = math.atan2(y, x)
            index = round((angle - scan.angle_min) / scan.angle_increment)
            if not 0 <= index < len(scan.ranges):
                return False
            value = scan.ranges[index]
            if not math.isfinite(value) or not scan.range_min <= value <= scan.range_max:
                return False
            if value < radius + .05:
                return False
    return True


def swept_clear(grid, x, y, yaw, dx, dy):
    """Check every intersecting grid cell against the swept, padded footprint.

    Translation keeps orientation fixed. Unknown and off-grid are unsafe;
    inflation is allowed, but inscribed (99) and lethal (100) are not.
    """
    c, s = math.cos(yaw), math.sin(yaw)
    bounds = (-0.50 + min(0, dx), 0.41 + max(0, dx),
              -0.25 + min(0, dy), 0.25 + max(0, dy))
    corners = [(x + a*c - b*s, y + a*s + b*c)
               for a in bounds[:2] for b in bounds[2:]]
    res = grid.info.resolution
    ox, oy = grid.info.origin.position.x, grid.info.origin.position.y
    pad = res * math.sqrt(2) / 2
    for gx in range(math.floor((min(p[0] for p in corners)-ox)/res)-1,
                    math.ceil((max(p[0] for p in corners)-ox)/res)+1):
        for gy in range(math.floor((min(p[1] for p in corners)-oy)/res)-1,
                        math.ceil((max(p[1] for p in corners)-oy)/res)+1):
            wx, wy = ox+(gx+.5)*res, oy+(gy+.5)*res
            a, b = (wx-x)*c+(wy-y)*s, -(wx-x)*s+(wy-y)*c
            if (bounds[0]-pad <= a <= bounds[1]+pad
                    and bounds[2]-pad <= b <= bounds[3]+pad):
                cost = cost_at(grid, wx, wy)
                if cost is None or cost < 0 or cost >= 99:
                    return False
    return True


def choose_recovery(grid, x, y, yaw, distance, scan=None):
    """Prefer the safe rear/side corridor with most extra free travel."""
    candidates = [(-distance, 0.0), (0.0, distance), (0.0, -distance)]
    safe = [p for p in candidates if swept_clear(grid, x, y, yaw, *p)
            and (scan is None or scan_covers_move(scan, *p))]
    if not safe:
        return None
    return max(safe, key=lambda p: sum(
        swept_clear(grid, x, y, yaw, p[0]*scale, p[1]*scale)
        for scale in (1.5, 2.0, 3.0)))
