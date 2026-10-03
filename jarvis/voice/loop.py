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
from typing import Callable
from pathlib import Path

from ..brain import Brain, Chunk, ToolRun
from ..providers import ProviderError
from ..tools import ToolRegistry
from .audio import CaptureError, Recorder
from .keys import KeyCombo, key_name_from_event, modifier_from_key
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
    # A single key ("f9") or a combination ("<ctrl>+<alt>+j"). A bare space was
    # the original default and is a bad one for a background assistant: it fires
    # on every keystroke.
    ptt_key: str = "f9"
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
        on_state: Callable[[str, str], None] | None = None,
        on_turn: Callable[[str, str], None] | None = None,
        on_tool: Callable[[object], None] | None = None,
        galaxy_bridge=None,
    ) -> None:
        self.brain = brain
        self.transcriber = transcriber
        self.speaker = speaker
        self.recorder = recorder or Recorder()
        self.config = config or VoiceConfig()
        self.registry = registry

        # Push-to-talk binding, parsed once. Supports single keys and combos.
        self._ptt = KeyCombo(self.config.ptt_key)
        self._held_modifiers: set[str] = set()

        # Observers. A GUI uses these to show what is happening without the
        # loop needing to know a GUI exists; the terminal path passes nothing
        # and gets its own printing.
        self._on_state_cb = on_state
        self._on_turn_cb = on_turn
        self._on_tool_cb = on_tool
        self._galaxy_bridge = galaxy_bridge

        self._ready: list[Path] = []
        self._ready_lock = threading.Lock()
        self._interrupt = threading.Event()
        self._quit = threading.Event()
        self._speaking = threading.Event()
        self._listener = None
        self._thread: threading.Thread | None = None

    # -- state reporting ----------------------------------------------------

    def _on_state(self, state: str, detail: str = "") -> None:
        """Report a state change to whoever is watching.

        The terminal prints; a GUI updates its panel. The loop itself does not
        care which — that is what keeps one voice core serving both.
        """
        # Write to the galaxy bridge first, so the galaxy always knows the
        # current state even if no observer is attached.
        if self._galaxy_bridge is not None:
            try:
                self._galaxy_bridge.set_state(state)
            except Exception:  # noqa: BLE001 - a broken bridge must not stop voice
                pass
        if self._on_state_cb is not None:
            try:
                self._on_state_cb(state, detail)
                return
            except Exception:  # noqa: BLE001 - a broken observer must not stop voice
                pass
        self._print_state(state, detail)

    def _print_state(self, state: str, detail: str = "") -> None:
        if state == "recording":
            print("\r● recording… (release to send)      ", end="", flush=True)
        elif state == "tooshort":
            print("\r(too short — key was tapped, not held)        ")
        elif state == "interrupted":
            print("\n[interrupted — listening]")
        elif state == "thinking":
            print("(thinking…)", end="", flush=True)
        elif state == "error":
            print(f"\n{detail or 'error'}")
        elif state == "transcribing":
            print("\r(transcribing…)                    ", end="", flush=True)

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
        # Track modifier state first, so a combo is matched against what is
        # actually held at the instant the trigger key goes down.
        modifier = modifier_from_key(key)
        if modifier:
            self._held_modifiers.add(modifier)
            return

        name = key_name_from_event(key)

        if name == self.config.interrupt_key:
            if self._speaking.is_set():
                # Barge-in: stop talking immediately.
                self.speaker.stop()
                self._interrupt.set()
                self._on_state("interrupted")
            else:
                self._quit.set()
                return False  # stop the listener
            return

        if not self._ptt.matches(name, self._held_modifiers):
            return

        # Holding the key while JARVIS is speaking is a barge-in: stop talking
        # and start listening. This is also what stops it hearing itself.
        if self._speaking.is_set():
            self.speaker.stop()
            self._interrupt.set()
            self._on_state("interrupted")

        try:
            if not self.recorder.recording:
                self.recorder.start()
                self._on_state("recording")
        except CaptureError as exc:
            self._on_state("error", f"cannot record: {exc}")

    def _on_release(self, key) -> None:
        modifier = modifier_from_key(key)
        if modifier:
            self._held_modifiers.discard(modifier)
            return

        name = key_name_from_event(key)
        if not self._ptt.matches(name, self._held_modifiers):
            return
        if not self.recorder.recording:
            return
        path = self.recorder.stop()
        if path is None:
            self._on_state("tooshort")
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
        # Write non-zero audio levels so the galaxy lights up while JARVIS speaks.
        if self._galaxy_bridge is not None:
            try:
                self._galaxy_bridge.set_audio_levels(0.6, 0.4, 0.2)
            except Exception:  # noqa: BLE001
                pass
        try:
            for event in brain_iter:
                if self._interrupt.is_set():
                    break

                if isinstance(event, ToolRun):
                    if self._on_tool_cb is not None:
                        try:
                            self._on_tool_cb(event)
                        except Exception:  # noqa: BLE001
                            pass
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
            # Reset audio levels so the galaxy goes back to idle.
            if self._galaxy_bridge is not None:
                try:
                    self._galaxy_bridge.set_audio_levels(0, 0, 0)
                except Exception:  # noqa: BLE001
                    pass
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
        self._on_state("transcribing")
        started = time.time()
        try:
            text = self.transcriber.transcribe(path)
        except TranscriptionError as exc:
            self._on_state("error", f"cannot transcribe: {exc}")
            return
        finally:
            if consume:
                path.unlink(missing_ok=True)

        if not text:
            self._on_state("heardnothing")
            return

        elapsed = time.time() - started
        # Report what it *thought* was said, always — so a wrong answer can be
        # traced to the ears or the brain.
        if self._on_turn_cb is not None:
            try:
                self._on_turn_cb("hears", text)
            except Exception:  # noqa: BLE001
                pass
        if self.config.show_transcript:
            print(f'\rhears › "{text}"  ({elapsed:.1f}s)')
        else:
            print()

        if self.config.thinking_cue:
            self._on_state("thinking")

        self._interrupt.clear()
        try:
            reply = self._speak_stream(self.brain.ask(text))
        except ProviderError as exc:
            self._on_state("error", f"brain unavailable: {exc}")
            return
        print()
        if not reply.strip():
            print("(no reply)")
        elif self._on_turn_cb is not None:
            try:
                self._on_turn_cb("replies", reply)
            except Exception:  # noqa: BLE001
                pass

    # -- external control ---------------------------------------------------
    # These are what a GUI drives. They exist so the window never has to reach
    # into the loop's internals, and so the same loop serves terminal and panel.

    def start(self) -> None:
        """Begin listening for the push-to-talk key and processing recordings."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._quit.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Stop listening and shut the loop down."""
        self._quit.set()
        thread = getattr(self, "_thread", None)
        if thread is not None:
            thread.join(timeout=timeout)
            self._thread = None
        self.speaker.stop()
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def submit_recording(self, path: Path) -> None:
        """Hand a finished recording to the loop to transcribe and answer."""
        with self._ready_lock:
            self._ready.append(path)

    def interrupt(self) -> None:
        """Cut off speech and go back to listening."""
        self.speaker.stop()
        self._interrupt.set()

    @property
    def running(self) -> bool:
        thread = getattr(self, "_thread", None)
        return thread is not None and thread.is_alive()

    # -- main loop ----------------------------------------------------------

    def _install_listener(self) -> bool:
        try:
            from pynput import keyboard
        except ImportError:
            self._on_state(
                "error", "push-to-talk needs pynput: .venv/bin/pip install pynput"
            )
            return False

        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener.start()
        return True

    def _run_loop(self) -> None:
        """Process finished recordings until told to stop."""
        while not self._quit.is_set():
            with self._ready_lock:
                pending = self._ready.pop(0) if self._ready else None
            if pending is None:
                time.sleep(0.03)
                continue
            self.handle_recording(pending)

    def run(self) -> int:
        """Terminal entry point: listen, print state, block until quit."""
        if not self._install_listener():
            return 2

        name = getattr(self.brain, "name", "JARVIS")
        if not self._ptt.is_valid:
            print(
                f"voice.ptt_key is not a usable binding: {self.config.ptt_key!r}\n"
                "  Use a single key like 'f9', or a combo like '<ctrl>+<alt>+j'.",
                file=sys.stderr,
            )
            return 2
        print(
            f"{name} is listening. Hold [{self._ptt.describe()}] to talk, "
            f"[{self.config.interrupt_key.upper()}] to interrupt or quit."
        )
        print("The typed interface is still available: run without --voice.\n")

        try:
            self._run_loop()
        except KeyboardInterrupt:
            print()
        finally:
            self.stop()

        print("Goodbye.")
        return 0
