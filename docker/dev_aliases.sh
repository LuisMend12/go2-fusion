# Shortcuts for working inside the container, sourced by every interactive shell.

# Rebuild the workspace (cb) or only the named packages (cbs pkg1 pkg2), then
# reload it so new executables are found. Only needed for C++ changes, new
# packages, or new entries in setup.py; Python edits need no rebuild.
cb() { (cd /ros2_ws && colcon build --symlink-install "$@") && source /ros2_ws/install/setup.bash; }
cbs() { cb --packages-select "$@"; }

alias teleop='ros2 run keyboard_teleop keyboard_teleop'
