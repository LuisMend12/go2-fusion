# Working on this repo

How the team develops: one Docker image that holds only the dependencies, your code mounted into it live, and small branches merged through pull requests.

Using an AI coding agent? It picks up the same rules from [AGENTS.md](AGENTS.md) (Codex, Cursor) or `CLAUDE.md` (Claude Code) automatically.

## One-time setup

```shell
git clone --recursive git@github.com:LuisMend12/go2_ros2_sdk.git
cd go2_ros2_sdk/docker
docker compose build
```

The first build takes a while (it downloads ROS packages, PyTorch and Open3D). After that the image only rebuilds when a dependency changes.

- Cloned without `--recursive`? Run `git submodule update --init --recursive`.
- On Windows, add `-f docker-compose.windows.yml` to every `docker compose` command. See [WINDOWS_SETUP.md](WINDOWS_SETUP.md).

## Start the robot stack

```shell
cd docker
ROBOT_IP=192.168.50.150 CONN_TYPE=webrtc docker compose up --build
```

`--build` costs nothing unless a dependency changed. On start the container builds the workspace (a few seconds after the first run), then launches `robot.launch.py`.

Open a shell inside the running container from another terminal:

```shell
docker compose exec unitree_ros bash
```

## The edit loop

Your repo folder is mounted into the container at `/ros2_ws/src`. Edit files on your machine as usual; the container sees the change immediately.

| What you changed | What to do |
| --- | --- |
| Python code in a node | Restart the node: Ctrl+C and rerun it, or `docker compose restart` for nodes started by the launch file. No rebuild. |
| C++ code, a new package, or a new executable in `setup.py` | In the container shell: `cbs <package>`, then restart the node |
| A dependency: `package.xml`, `requirements.txt`, `Dockerfile` | `docker compose up --build` |

Why Python needs no rebuild: colcon builds with `--symlink-install`, so `install/` holds shortcuts to your source files rather than copies.

Shortcuts inside the container:

| Command | Does |
| --- | --- |
| `cb` | Build the whole workspace |
| `cbs <pkg> [pkg...]` | Build only the named packages |
| `teleop` | Drive the robot from the keyboard |

If the build ever gets into a strange state, `docker compose down -v` deletes the build output; the next start rebuilds from scratch in about a minute.

## Branches and pull requests

1. Start every piece of work on its own branch. Never commit to `master`.
   ```shell
   git fetch
   git switch -c feat/<short-name> origin/master
   ```
2. Keep it small: one feature or fix per branch, merged within days. If two people need to change the same lines, do one first.
3. Before opening a PR, replay your work on top of the latest `master`:
   ```shell
   git fetch
   git rebase origin/master
   git push -u origin feat/<short-name>    # add --force-with-lease if you pushed before the rebase
   ```
4. Open a pull request. A teammate reviews it, then it's merged and the branch deleted.
5. Everyone else picks it up with `git fetch && git rebase origin/master` on their own branch.

## Design rules

- **Extend before adding.** Before creating a new node or topic, check whether an existing one should own it. Robot commands go on `/webrtc_req`, speech on `/tts`. Motion goes on a twist_mux input: each drive source has its own (`/cmd_vel_joy`, `/cmd_vel_keyboard`, `/cmd_vel` for Nav2, `/cmd_vel_agent`, `/cmd_vel_object_nav`; see `go2_robot_sdk/config/twist_mux.yaml`), so a new one gets a new input rather than sharing.
- **One ROS 2 distro for everyone:** Humble.
- **Test without the robot first.** There is one dog and it accepts one connection at a time. Check what your code sends with `ros2 topic echo /cmd_vel_keyboard` (or whichever topic you publish), and save lab time for the final check.
