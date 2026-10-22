---
title: LLM agent
parent: brains
code: [src/go2_llm_agent/**]
---

# LLM agent

The LLM agent lets you type a plain-English command like "walk forward for three seconds then turn left" and have Oak do it, so people can talk to Oak instead of steering it.

Part of: [Brains](brains.md)

## How it works

An *LLM* (large language model) is the kind of AI behind chatbots. The agent hands your sentence to the model, and the model answers with a short plan: a list of steps such as "walk forward 3 s" and "turn left 90 degrees". The agent then runs each step by publishing speeds on its own drive topic.

**Two versions exist right now.**

- **On `master` (Riley's original):** built by Riley Francis on OpenAI's paid GPT-4o-mini, using the LangChain and LangGraph libraries. We brought it in almost as-is. Its Python libraries are deliberately not installed in our Docker image, so it builds but `ros2 run` fails on missing imports.
- **On branch `adib/feat/llm-agent` (the team's direction):** Adib replaced the paid model with **Ollama**, a free program that runs AI models on your own computer, running a small **Qwen** model (`qwen3:4b-instruct-2507-q4_K_M`). No API key and no extra Python libraries are needed.

In Adib's version, a local checker validates every plan before anything moves: at most 4 steps, each timed move at most 5 s, walking at 0.2 m/s and turning at 0.5 rad/s. If any part of a request is unsupported, nothing runs. Typing `stop` cancels right away, without waiting for the model. Angle turns ("turn left 90 degrees") watch Oak's heading on `/odom` and stop when the turn is done, instead of guessing from time.

Example, in simulation (the default, which moves nothing):

```text
go2> walk backward for one second
[SIMULATION] velocity: forward=-0.2 m/s, left-turn=0 rad/s
Completed; stopped.
```

An older plan to rebuild the agent on Anthropic's Claude ([plan file](../plans/pending/2026-10-08-claude-llm-agent.md)) is **superseded** by the Ollama direction. Adib's branch marks it as historical context only.

## Connects to

- [twist_mux](twist-mux.md): the agent drives on `/cmd_vel_agent`, priority 4. The gamepad (10), keyboard (9) and Nav2 (5) all override it.
- [Posture](posture.md): Riley's version also sends sit, stand and stretch on `/webrtc_req`. Adib's version leaves posture out for now.
- [Voice](voice.md): Riley's version had a small web server (`speech_bridge`, `POST /command` on port 8000) that the microphone tool sends text to. Adib's branch disables it; typed commands come first.
- [Object detection](object-detection.md): Riley's `look_for_object` was meant to ask the detector what it sees, but it only works in mock mode.
- [Roadmap](roadmap.md) and [Decisions](decisions.md): why the agent changed direction.

## How it breaks

From Riley's version, as recorded in the package README and the old plan:

- It crashes without `OPENAI_API_KEY`, even in mock mode, because the AI client is created on import.
- `look_for_object` always errors in live mode.
- The plan is fixed before anything runs, turn direction can get lost ("turn right" turns left), and there is no stop and no speed cap.

From Adib's branch README:

- **Cannot reach Ollama:** keep the Ollama app running and check from inside Docker with `ros2 run go2_llm_agent agent --check`.
- **Turns report missing heading:** `/odom` is not arriving. Fix the driver side; the agent will not fake a turn by time.
- On an 8 GB Mac, heading checks sometimes timed out while Qwen was loaded, and passed once it was unloaded. Use `--timeout 60 --keep-alive 0` there.
- `stop` only stops this agent. It is not an emergency stop for all of Oak.

## Who's on it and what's next

**Adib** built the Ollama version and tested it in mock mode; the team update says it was also tried on Oak. Next, Adib moves to odometry reliability (why position data sometimes stops) and turn accuracy (requested vs measured rotation). TODO(Adib): when the branch merges into `master`. Its packages sit at the repo root (the layout before packages moved into `src/`), so it needs a rebase first.

## The code

Folder: https://github.com/maxhawksby/go2-fusion/tree/master/src/go2_llm_agent

Adib's version (from his branch README), inside the Docker container:

```shell
ros2 run go2_llm_agent agent --check                 # is Ollama reachable, is the model installed?
ros2 run go2_llm_agent agent                         # type at the go2> prompt; simulation only
ros2 run go2_llm_agent agent --plan-only --command "walk forward for 3 seconds then turn left"
python3 -m unittest discover -s /ros2_ws/src/go2_llm_agent/test -p test_agent.py -v
```

It only publishes to ROS with `--mode ros`. Do that only in the lab, next to Oak, with the keyboard ready.

<!-- sources: src/go2_llm_agent/README.md; docs/FUSION.md rows 2, 3, 11 and "Decided after the fusion"; docs/plans/pending/2026-10-08-claude-llm-agent.md; origin/adib/feat/llm-agent (38a6980: go2_llm_agent/README.md, commands.py, agent.py, FUSION.md and plan-file diffs); AGENTS.md; team update (Adib) week of 2026-10-18 -->
