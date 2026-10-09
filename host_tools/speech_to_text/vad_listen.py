import collections
import io
import json
import queue
import sys
import time
import wave

import numpy as np
import requests
import sounddevice as sd
import webrtcvad
from faster_whisper import WhisperModel

# CONFIG
RATE = 16000
CHANNELS = 1
DTYPE = "int16"

FRAME_MS = 30                  # must be 10, 20, or 30 for webrtcvad
FRAME_SAMPLES = int(RATE * FRAME_MS / 1000)
FRAME_BYTES = FRAME_SAMPLES * 2  # int16 = 2 bytes

VAD_MODE = 3                   # 0-3, higher = stricter
START_SPEECH_FRAMES = 3        # require this many voiced frames to start
END_SILENCE_MS = 900           # stop after this much silence
MAX_UTTERANCE_SEC = 8          # hard cap
PRE_ROLL_MS = 300              # keep some audio from before speech starts

POST_URL = "http://localhost:8000/command"

WHISPER_MODEL = "base"         # try "tiny" for lower latency
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE = "int8"


# SETUP
vad = webrtcvad.Vad(VAD_MODE)
audio_queue: queue.Queue[bytes] = queue.Queue()

model = WhisperModel(
    WHISPER_MODEL,
    device=WHISPER_DEVICE,
    compute_type=WHISPER_COMPUTE,
)

pre_roll_frames = max(1, PRE_ROLL_MS // FRAME_MS)
end_silence_frames = max(1, END_SILENCE_MS // FRAME_MS)
max_frames = int((MAX_UTTERANCE_SEC * 1000) // FRAME_MS)

def audio_callback(indata, frames, time_info, status):
    if status:
        print(f"[audio status] {status}", file=sys.stderr)
    audio_queue.put(bytes(indata))

def pcm_to_wav_bytes(pcm_bytes: bytes) -> io.BytesIO:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)  # int16
        wf.setframerate(RATE)
        wf.writeframes(pcm_bytes)
    buf.seek(0)
    return buf

def transcribe_pcm(pcm_bytes: bytes) -> str:
    wav_buf = pcm_to_wav_bytes(pcm_bytes)
    segments, info = model.transcribe(
        wav_buf,
        beam_size=1,
        vad_filter=False,   # we already did VAD ourselves
    )
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return text

def send_text(text: str):
    try:
        r = requests.post(
            POST_URL,
            json={"text": text},
            timeout=5,
        )
        print(f"[send] {r.status_code} {r.text}")
    except Exception as e:
        print(f"[send error] {e}")

def is_speech(frame_bytes: bytes) -> bool:
    return vad.is_speech(frame_bytes, RATE)

def main():
    print("Listening... speak to issue a command.")
    print("Press Ctrl+C to stop.\n")

    pre_roll = collections.deque(maxlen=pre_roll_frames)

    recording = False
    speech_run = 0
    silence_run = 0
    utterance_frames: list[bytes] = []

    with sd.RawInputStream(
        samplerate=RATE,
        blocksize=FRAME_SAMPLES,
        dtype=DTYPE,
        channels=CHANNELS,
        callback=audio_callback,
    ):
        try:
            while True:
                frame = audio_queue.get()

                if len(frame) != FRAME_BYTES:
                    continue

                voiced = is_speech(frame)
                pre_roll.append(frame)

                if not recording:
                    if voiced:
                        speech_run += 1
                    else:
                        speech_run = 0

                    if speech_run >= START_SPEECH_FRAMES:
                        recording = True
                        silence_run = 0
                        utterance_frames = list(pre_roll)
                        print("Speech detected...")
                    continue

                # recording mode
                utterance_frames.append(frame)

                if voiced:
                    silence_run = 0
                else:
                    silence_run += 1

                too_long = len(utterance_frames) >= max_frames
                enough_silence = silence_run >= end_silence_frames

                if enough_silence or too_long:
                    pcm_bytes = b"".join(utterance_frames)
                    recording = False
                    speech_run = 0
                    silence_run = 0
                    utterance_frames = []

                    print("End of speech. Transcribing...")
                    text = transcribe_pcm(pcm_bytes)
                    print(f"Transcript: {text!r}")

                    if text:
                        send_text(text)

                    print("\nListening again...\n")

        except KeyboardInterrupt:
            print("\nStopped.")

if __name__ == "__main__":
    main()
