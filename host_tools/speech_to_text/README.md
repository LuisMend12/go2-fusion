# Speech to text (host tool)

`vad_listen.py` lets you talk to the robot. It listens to your microphone, notices
when you start and stop speaking, turns the speech into text with Whisper, and sends
the text to the LLM agent's speech bridge (`go2_llm_agent`'s `speech_bridge`, at
`http://localhost:8000/command`).

**It runs on your own computer, outside Docker.** The container cannot reach your
microphone reliably, so this is plain Python on the host, not a ROS package. Mic access
is easiest from Windows Python; WSL microphone support is flaky.

Written by Riley Francis in
[ROS2-LLM-Nav](https://github.com/RileyFrancis/ROS2-LLM-Nav) (`host_tools/speech_to_text/`).

## Setup (once)

```shell
cd host_tools/speech_to_text
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

The first run downloads the Whisper `base` model (about 150 MB), so it needs internet once.

## Run

1. Start the stack and the speech bridge inside the container:
   `ros2 run go2_llm_agent speech_bridge` (see [go2_llm_agent/README.md](../../go2_llm_agent/README.md)).
   It listens on port 8000; the compose file uses host networking, so `localhost:8000`
   reaches it on Linux/WSL. On Docker Desktop for Windows, also publish port 8000 in
   `docker-compose.windows.yml`.
2. On the host: `python vad_listen.py`, then speak a command ("walk forward then sit").
   Ctrl+C stops it.

Settings (Whisper model size, silence timeout, bridge URL) are constants at the top of
`vad_listen.py`. Use `WHISPER_MODEL = "tiny"` for lower latency.
