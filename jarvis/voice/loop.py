"""Push-to-talk voice loop.

Hold the key, speak, release. The recorded audio is transcribed, the text is fed
to the same brain the typed interface uses, and the reply is spoken as it is
generated — first sentence out loud while the rest is still being written.

Latency notes that shaped this design:
  * The reply is spoken in sentences, not all at once, so the first words start
    playing long before the model has finished.
  * A "thinking" cue fires the moment the key is released, so silence never
    reads as "it broke".
  * Transcription is printed next to the reply while building, so when it
    answers the wrong question you can see whether the ears or the brain erred.
"""

from __future__ import annotations

import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..brain import Brain, Chunk, ToolRun
from ..providers import ProviderError
from ..tools import ToolRegistry
from .audio import CaptureError, Recorder
from .stt import Transcriber, TranscriptionError
from .tts import Speaker, SpeechError

# Split streamed text into speakable sentences. Speaking on sentence boundaries
# rather than per token is what makes the voice sound deliberate instead of
# stuttering.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")


def split_sentences(buffer: str) -> tuple[list[str], str]:
    """Pull complete sentences out of a growing buffer.

    Returns (complete sentences, remainder to keep buffering).
    """
    parts = _SENTENCE_END.split(buffer)
    if len(parts) <= 1:
        return [], buffer
    return [p.strip() for p in parts[:-1] if p.strip()], parts[-1]


@dataclass
class VoiceConfig:
    ptt_key: str = "space"
    interrupt_key: str = "esc"
    speak_replies: bool = True
    show_transcript: bool = True
    thinking_cue: bool = True
    # Don't speak sentences shorter than this — avoids blurting "OK."
    min_sentence_chars: int = 2


class VoiceLoop:
    def __init__(
        self,
        brain: Brain,
        transcriber: Transcriber,
        speaker: Speaker,
        recorder: Recorder | None = None,
        config: VoiceConfig | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.brain = brain
        self.transcriber = transcriber
        self.speaker = speaker
        self.recorder = recorder or Recorder()
        self.config = config or VoiceConfig()
        self.registry = registry

        self._ready: list[Path] = []
        self._ready_lock = threading.Lock()
        self._interrupt = threading.Event()
        self._quit = threading.Event()
        self._speaking = threading.Event()
        self._listener = None

    # -- keyboard -----------------------------------------------------------

    def _key_name(self, key) -> str:
        """A stable name for a pressed key, across pynput's Key and KeyCode."""
        try:
            from pynput import keyboard
        except ImportError:  # pragma: no cover
            return ""

        if isinstance(key, keyboard.Key):
            return key.name
        char = getattr(key, "char", None)
        return char.lower() if char else ""

    def _on_press(self, key) -> None:
        name = self._key_name(key)

        if name == self.config.interrupt_key:
            if self._speaking.is_set():
                # Barge-in: stop talking immediately.
                self.speaker.stop()
                self._interrupt.set()
                print("\n[interrupted]")
            else:
                self._quit.set()
                return False  # stop the listener
            return

        if name != self.config.ptt_key:
            return

        # Holding the key while JARVIS is speaking is a barge-in: stop talking
        # and start listening. This is also what stops it hearing itself.
        if self._speaking.is_set():
            self.speaker.stop()
            self._interrupt.set()
            print("\n[interrupted — listening]")

        try:
            if not self.recorder.recording:
                self.recorder.start()
                print("\r● recording… (release to send)      ", end="", flush=True)
        except CaptureError as exc:
            print(f"\n[cannot record] {exc}")

    def _on_release(self, key) -> None:
        if self._key_name(key) != self.config.ptt_key:
            return
        if not self.recorder.recording:
            return
        path = self.recorder.stop()
        if path is None:
            print("\r(too short — key was tapped, not held)        ")
            return
        with self._ready_lock:
            self._ready.append(path)

    # -- speaking -----------------------------------------------------------

    def _speak_stream(self, brain_iter) -> str:
        """Consume the brain's stream, speaking whole sentences as they form.

        Returns the full reply text. Stops early if the user interrupts.
        """
        buffer = ""
        spoken_all: list[str] = []
        self._speaking.set()
        try:
            for event in brain_iter:
                if self._interrupt.is_set():
                    break

                if isinstance(event, ToolRun):
                    status = "ok" if event.ok else "FAILED"
                    print(f"  · {event.name} → {status}")
                    continue
                if not isinstance(event, Chunk):
                    continue

                print(event.text, end="", flush=True)
                spoken_all.append(event.text)
                buffer += event.text

                sentences, buffer = split_sentences(buffer)
                for sentence in sentences:
                    if self._interrupt.is_set():
                        break
                    if len(sentence) >= self.config.min_sentence_chars:
                        try:
                            self.speaker.speak(sentence)
                        except SpeechError as exc:
                            print(f"\n[cannot speak] {exc}")
                            return "".join(spoken_all)

            # Whatever is left, if the user did not cut us off.
            tail = buffer.strip()
            if tail and not self._interrupt.is_set():
                try:
                    self.speaker.speak(tail)
                except SpeechError as exc:
                    print(f"\n[cannot speak] {exc}")
        finally:
            self._speaking.clear()
        return "".join(spoken_all)

    # -- one spoken turn ----------------------------------------------------

    def handle_recording(self, path: Path, consume: bool = True) -> None:
        """Run one complete spoken turn from a recording.

        Public so the whole path can be exercised from a file, with no
        microphone involved — the most useful way to debug voice.

        `consume` deletes the recording once it has been transcribed. That is
        right for a real capture (the file is disposable) but wrong for a test
        fixture you want to reuse, so the CLI passes consume=False.
        """
        print("\r(transcribing…)                    ", end="", flush=True)
        started = time.time()
        try:
            text = self.transcriber.transcribe(path)
        except TranscriptionError as exc:
            print(f"\r[cannot transcribe] {exc}")
            return
        finally:
            if consume:
                path.unlink(missing_ok=True)

        if not text:
            print("\r(heard nothing)                    ")
            return

        elapsed = time.time() - started
        # Print what it *thought* was said, always — so a wrong answer can be
        # traced to the ears or the brain.
        if self.config.show_transcript:
            print(f'\rhears › "{text}"  ({elapsed:.1f}s)')
        else:
            print()

        if self.config.thinking_cue:
            print("(thinking…)", end="", flush=True)

        self._interrupt.clear()
        try:
            reply = self._speak_stream(self.brain.ask(text))
        except ProviderError as exc:
            print(f"\n[brain unavailable] {exc}")
            return
        print()
        if not reply.strip():
            print("(no reply)")

    # -- main loop ----------------------------------------------------------

    def run(self) -> int:
        try:
            from pynput import keyboard
        except ImportError:
            print(
                "Push-to-talk needs pynput.\n"
                "  Install it with: .venv/bin/pip install pynput",
                file=sys.stderr,
            )
            return 2

        name = getattr(self.brain, "name", "JARVIS")
        print(f"{name} is listening. Hold [{self.config.ptt_key.upper()}] to talk, "
              f"[{self.config.interrupt_key.upper()}] to interrupt or quit.")
        print("The typed interface is still available: run without --voice.\n")

        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener.start()

        try:
            while not self._quit.is_set():
                with self._ready_lock:
                    pending = self._ready.pop(0) if self._ready else None
                if pending is None:
                    time.sleep(0.03)
                    continue
                self.handle_recording(pending)
        except KeyboardInterrupt:
            print()
        finally:
            self._quit.set()
            self.speaker.stop()
            if self._listener is not None:
                self._listener.stop()

        print("Goodbye.")
        return 0
