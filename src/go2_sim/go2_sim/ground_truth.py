"""Write the ground-truth map of a world (map_server PGM + YAML).

    ros2 run go2_sim ground_truth <world name or .sdf> [output.yaml]

Useful to check a new world: open the .pgm and see that walls and furniture
are where they should be. Ship it as <world>.gt.yaml next to the world file
when the world uses meshes the generator cannot read.
"""

import os
import sys

from go2_sim import world_tools


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return
    world = argv[0]
    if not world.endswith('.sdf'):
        from ament_index_python.packages import get_package_share_directory
        world = os.path.join(get_package_share_directory('go2_sim'), 'worlds', world + '.sdf')
    with open(world) as f:
        obstacles, skipped = world_tools.load_obstacles(f.read())
    for s in skipped:
        print(f'warning: not in the ground truth (not a box or cylinder): {s}')
    grid = world_tools.rasterize(obstacles)
    out = argv[1] if len(argv) > 1 else os.path.splitext(os.path.basename(world))[0] + '.gt.yaml'
    pgm = world_tools.write_map(grid, out)
    inside = world_tools.interior_mask(grid).sum() * grid.resolution ** 2
    print(f'wrote {out} and {pgm}: {len(obstacles)} obstacles, '
          f'{inside:.1f} m2 of floor inside the building')


if __name__ == '__main__':
    main()
