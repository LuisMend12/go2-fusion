"""Watch headless trials live: a Gazebo window and RViz on the running trial.

    ros2 run go2_sim watch               # Gazebo + RViz
    ros2 run go2_sim watch --no-gazebo   # RViz only: the light choice without a GPU
    ros2 run go2_sim watch --no-rviz     # Gazebo only

Run it in the same container as `ros2 run go2_sim trials`. It reads which ROS
domain and Gazebo partition the current run uses (the trial runner writes them
to /tmp/go2_sim_current_run.json), opens the windows on that run, and moves to
the next run when one ends. Close it any time with Ctrl+C: the trials keep
going, since the windows only look and never send anything.
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time

from go2_sim.trials import CURRENT_RUN_FILE


def read_current():
    try:
        with open(CURRENT_RUN_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def stop(procs):
    for p in procs:
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    for p in procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)


def open_windows(info, rviz, gazebo):
    from ament_index_python.packages import get_package_share_directory
    env = os.environ.copy()
    env.update(ROS_DOMAIN_ID=str(info['ROS_DOMAIN_ID']), ROS_LOCALHOST_ONLY='1',
               IGN_PARTITION=info['IGN_PARTITION'])
    share = get_package_share_directory('go2_sim')
    env['IGN_GAZEBO_RESOURCE_PATH'] = os.pathsep.join(
        p for p in (os.path.join(share, 'models'), os.path.join(share, 'worlds'),
                    env.get('IGN_GAZEBO_RESOURCE_PATH', '')) if p)
    quiet = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                 env=env, start_new_session=True)
    # On a Mac, windows go through docker/mac's mac-gui (VirtualGL to XQuartz).
    window = ['mac-gui'] if shutil.which('mac-gui') else []
    procs = []
    if gazebo:
        procs.append(subprocess.Popen(window + ['ign', 'gazebo', '-g'], **quiet))
    if rviz:
        config = os.path.join(get_package_share_directory('go2_robot_sdk'),
                              'config', 'single_robot_conf.rviz')
        procs.append(subprocess.Popen(window + ['rviz2', '-d', config], **quiet))
    return procs


def _interrupt(_signum, _frame):
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--no-rviz', action='store_true', help='Gazebo window only')
    parser.add_argument('--no-gazebo', action='store_true',
                        help='RViz only: without a GPU the Gazebo window halves the speed')
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
        sys.exit('No display: windows need DISPLAY (see docs/wiki/wsl.md).')

    # SIGTERM (docker stop, kill) closes the windows too, like Ctrl+C.
    signal.signal(signal.SIGTERM, _interrupt)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    current, procs = None, []
    print('[watch] waiting for a trial run...', flush=True)
    try:
        while True:
            info = read_current()
            key = info and (info.get('run'), info.get('IGN_PARTITION'))
            if key != current:
                stop(procs)
                procs = []
                current = key
                if info:
                    print(f"[watch] run {info['run']}/{info['runs']}: opening windows",
                          flush=True)
                    # Give the run's Gazebo server a moment to start.
                    time.sleep(3)
                    procs = open_windows(info, rviz=not args.no_rviz,
                                         gazebo=not args.no_gazebo)
                else:
                    print('[watch] run ended; waiting for the next one...', flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop(procs)


if __name__ == '__main__':
    main()
