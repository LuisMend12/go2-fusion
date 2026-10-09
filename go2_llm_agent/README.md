# go2_llm_agent

Type or say a plain-English command ("walk forward then sit") and the robot does it.
GPT-4o-mini (through LangChain and LangGraph) turns the request into a short plan of
robot actions, then runs each step.

Written by Riley Francis in [ROS2-LLM-Nav](https://github.com/RileyFrancis/ROS2-LLM-Nav).

> **Pending decision: this package does not run in the Docker image yet.** It was brought
> in as-is (only its drive topic and sit message were changed; see [FUSION.md](../FUSION.md)).
> The team is deciding whether to keep it on OpenAI or rebuild it on Claude, so its pip
> dependencies (`requirements.txt`: langchain, langgraph, fastapi, ...) are deliberately
> **not** installed in the image. It builds with colcon, but `ros2 run` fails on the
> missing imports until that decision is made.

## Modules

| Module | Description |
|--------|-------------|
| `agent.py` | Plans and executes multiple motion commands from one natural-language request |
| `ros2_motion.py` | Live motion backend: publishes `/cmd_vel_agent` (its twist_mux input), `/tts` and `/webrtc_req` |
| `ros2_mock_motion.py` | Mock backend that prints commands instead of moving the robot |
| `speech_bridge.py` | FastAPI server (`POST /command`) that feeds transcripts to the agent |

## Topics (live mode only)

| Topic | Type | What |
| --- | --- | --- |
| `/cmd_vel_agent` | `geometry_msgs/Twist` | Walk and turn (twist_mux priority 4: joystick, keyboard and Nav2 override it) |
| `/webrtc_req` | `go2_interfaces/WebRtcReq` | Sport API: stand up 1004, stand down 1005, recovery stand 1006, sit 1009, stretch 1017 |
| `/tts` | `std_msgs/String` | Text for `speech_processor`'s `tts_node` to speak |

It subscribes to nothing. In mock mode (the default) it publishes nothing at all.

## Agent actions

| Tool | What it does |
| --- | --- |
| `walk` | Walk forward for a duration at a speed |
| `turn_in_place` | Rotate in place |
| `sit` | Sit, wait, then recovery stand |
| `stretch` | Stretch, wait, then recovery stand |
| `stand_up`, `stand_down`, `recovery_stand` | Posture commands |
| `look_for_object` | Ask whether an object is visible (mock mode only, see Known issues) |

The planner returns a `Plan` (a list of `Step`s, each an action plus optional
`duration_s`/`label`); the executor then calls exactly one tool per step.

## Setup

Set these in the environment (or a `.env` file in the directory you run from, which is
gitignored; never commit the key):

```
OPENAI_API_KEY="your-api-key-here"
ROBOT_ENV=testing   # or: live
```

`ROBOT_ENV` defaults to `testing`, which uses the mock backend and never moves the robot.
Set `ROBOT_ENV=live` to drive the real robot.

## Running

```bash
ros2 run go2_llm_agent agent            # interactive text prompt
ros2 run go2_llm_agent speech_bridge    # HTTP bridge on port 8000
```

Test the bridge without a microphone:

```bash
curl -X POST http://localhost:8000/command -H "Content-Type: application/json" \
  -d '{"text":"walk forward for one second"}'
```

For voice, run [host_tools/speech_to_text](../host_tools/speech_to_text/README.md) on the
host. For speech out, start `ros2 run speech_processor tts_node` with an ElevenLabs key.

Live mode safety: start with tiny moves ("walk forward for half a second"), in an open
area, with the keyboard or joystick ready; both override the agent.

## Adding an action

1. Add a method to both backends: `MockMotionController` (`ros2_mock_motion.py`) and
   `RosMotionController` (`ros2_motion.py`).
2. Add an `@tool` wrapper in `agent.py` and put it in the `tools` list.
3. Add its name to `Step.action`'s `Literal` and to the planner's system prompt.
4. Test with `ROBOT_ENV=testing` first, then live at low speed.

## Known issues (left as Riley wrote them, pending the rebuild decision)

- `ChatOpenAI(...)` is created when `agent.py` is imported, so it crashes without
  `OPENAI_API_KEY` even in mock mode.
- `look_for_object` calls `find_object()`, which only the mock backend has. In live mode
  that tool always errors; it is not wired to `object_detection` yet. A fix would
  subscribe to `/detected_objects_dict` and look the label up there.
- Importing `agent.py` (which `speech_bridge` does) starts the motion backend as a side
  effect.
- `ros2_motion.py` has an unused `dance()` stub.
