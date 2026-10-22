# Robot test log

One section per lab session, newest first. Each test gets a result (pass, fail, partial, not run) and what we saw.
Open issues at the bottom carry over between sessions until they're fixed and retested.
Claude updates this during a session from Max's feedback and what it measures, and commits it at the end.

## 2026-10-11 - ISL lab, Oak, Wi-Fi (WebRTC)

Code: `master` at `61de971` (fusion + Luis's Oct 9-11 work), then branch `fix/keyboard-panel-idle`.
Earlier tests ran on `f85e703` (fusion before Luis's update); marked "old code" below.

| Test | Result | What we saw |
| --- | --- | --- |
| Build in Docker | pass | The first attempt ran out of memory and crashed WSL (7.4 GB, 16 parallel compiles, two builds at once). It built fine with `MAKEFLAGS=-j4 colcon build --parallel-workers 2`. |
| Connect, camera, RViz | pass | |
| Lidar `/point_cloud2` | pass | About 6.8 Hz. The 3D voxel view in RViz works. |
| Lidar topic mismatch | check | The driver publishes `/point_cloud2`, nothing publishes `/robot0/point_cloud2`, and `lidar_to_pointcloud` wasn't running in the default launch. Luis's remap is in; check which launch option starts that node. |
| Keyboard teleop (terminal) | partial | The dog moves and stops, but it "really isn't that good". Likely cause: the bugs below (stops dropped, idle zeros). Retest. |
| YOLO `object_detection` | pass | About 4.5 fps on CPU, 55-130 ms per frame. Saw person 0.86 and chair 0.34. View it at `/detections/image_annotated`. |
| twist_mux priority | pass | Object nav forward, then keyboard turn wins, then object nav resumes, then stop. Checked on `/cmd_vel_out`. |
| Stop at end of drive (old code) | **fail** | **The dog kept walking and hit a wall.** The driver dropped every zero `cmd_vel`, so stop never reached the robot. This is fixed by Luis's `robot_control_service.py` change, now on `master`. |
| Stop at end of drive (new code) | pass, confirm | Stop was delivered. Odom shows the dog moved 0.11 m in the 2 s after the stop (slowing down, not walking on). Max to confirm by eye. |
| RViz KeyboardTeleop panel idle | **fail, fixed** | The panel sent zeros about 4 times a second on `/cmd_vel_keyboard` (priority 9), which blocked Nav2, the agent and object nav. The terminal `keyboard_teleop` did the same at 10 Hz. Both now publish only while a key is held, plus one stop. On `fix/keyboard-panel-idle`. |
| Nav2 goal (old code) | fail | "Starting point in lethal space": the lidar marks the dog's own body as an obstacle. Luis's costmap `min_range: 0.1` should fix it. Retest. |
| Data stall after Ctrl+C | note | Camera kept streaming, but lidar and odom went silent. `docker compose -p go2fusion up -d --force-recreate` recovered it. |
| Gamepad LB deadman | not run | No Xbox-style gamepad. The lab uses Unitree's R3-1 remote, which bypasses ROS. |
| Not run yet | - | MapViewer click-to-walk, object nav to a chair, sit/stand, AutoMapper, TTS (needs an ElevenLabs key), Claude agent (not built). |

## Open issues

1. Retest Nav2 goals and MapViewer click-to-walk on new code.
2. Retest keyboard driving feel with both teleop fixes.
3. Find out what starts `lidar_to_pointcloud` and whether its input topic is right.
4. Confirm by eye that the dog stops cleanly when a drive source goes quiet.
5. WSL has 7.4 GB RAM: keep builds at `-j4` / 2 workers, or raise `memory=` in `.wslconfig`.
6. Gamepad LB deadman: no longer required. The team no longer uses an Xbox gamepad; it drives with the Oak ROS2 pad, which sends signals differently. `TODO(Max): how the Oak ROS2 pad connects (does it publish /joy into ROS, or talk to Oak directly?)`
