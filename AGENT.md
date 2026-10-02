# JARVIS — Agent Spec

> Single source of truth for what we're building and why. Written at the end of
> Tier 0 (the interview). Update it when a decision changes; don't let it drift.

## What it is

**JARVIS** — a voice-first personal assistant that runs on my laptop, can act on
my behalf through tools, remembers me across restarts, and can reach out first
when something is worth my attention.

Built for **me, just me** (single user). Per-user state is not needed yet, but
the design should not make it hard later.

## Personality

**Crisp and professional.** Direct, competent, no filler. Short sentences.
States what it did and what it needs. Consistent everywhere — text, voice,
logs, and any proactive notice.

## First three capabilities

These are the first tools and the first test cases. Everything else comes later.

1. **Answering messages** — read/draft/send messages on my behalf.
   *(Sending is consequential: always gated, never automatic.)*
2. **Opening and managing apps, notes, and documents** — launch apps, find,
   open, create, and organize notes and files.
   *(Opening is safe; deleting or overwriting is consequential.)*
3. **Telling time and weather** — current time/date, and current conditions or
   forecast for a place.

## Stack

| Decision | Choice | Why |
|---|---|---|
| Language | **Python 3.14** | Boring, well-supported, good audio + HTTP libraries. |
| Runtime | Local venv at `jarvis/.venv` | Self-contained; no global installs. |
| Framework | **None** | Small, readable harness. Stdlib + `httpx` + `pyyaml` only. |
| Brain provider | **Gemini** (`gemini-3.5-flash`) via the REST API | Chosen by user (Gemini 3 Pro). Behind a thin provider seam so it can be swapped. |
| Model name | In `config.yaml` | Not hardcoded — one-line change to swap models. |
| STT | Deepgram (Tier 3) | Fast, accurate, streams. Behind its own seam. |
| TTS | ElevenLabs (Tier 3) | Natural voice, streams. Behind its own seam. |

> **Note on the model ID.** The user asked for **Gemini 3 Pro**. Two problems
> were found and verified against the live API with this key:
>
> 1. `gemini-3-pro-preview` has been **shut down** by Google.
> 2. Its replacement, `gemini-3.1-pro-preview`, is visible to the key but has
>    **zero quota on a free-tier plan** — every call returns
>    `429 RESOURCE_EXHAUSTED`. The key itself is fine.
>
> Verified working on this key: **`gemini-3.5-flash`**, `gemini-3.5-flash-lite`
> and `gemini-3.6-flash`. The free tier also enforces a **daily** request cap
> shared across models — a heavy day can exhaust it, in which case switch model
> in `config.yaml` or wait for the reset at midnight Pacific. Default is
> `gemini-3.5-flash`. Moving to a Pro model is a **one-line change** once Pro
> quota is available.

## Where it runs

**Laptop-first.** Tier 5's heartbeat is built as a cleanly separable loop so it
can be relocated to an always-on host later without a rewrite — but no server is
required to start.

## How I talk to it

- **Tier 1–2:** typed text in a terminal.
- **Tier 3:** **push-to-talk** (hold a key, speak, release). This is built
  *after* the text brain works, regardless of the long-term goal, because it is
  the most reliable path and the cheapest to debug.
- **Wake word:** the user asked for **open-mic wake word from the start**. This
  is deliberately *deferred* past Tier 3, per the build rule that voice is a
  layer on a working text agent. Wake word is the last voice milestone, not the
  first — it adds the most failure modes (self-listening, false triggers) and
  should land only once push-to-talk is solid. The name "JARVIS" is the intended
  wake phrase.
- **The typed interface stays alive forever.** It is the debugging path and the
  fallback when audio misbehaves.

## Never without asking first

Every one of these requires an explicit, per-action **yes** before it runs —
from spoken, typed, or heartbeat-initiated turns alike. Confirmation never
generalizes: approving one action does not pre-authorize the next.

1. **Spend money** — any purchase, payment, subscription, or billing change.
2. **Send messages** — any email, text, chat, or post that leaves the machine
   under my identity.
3. **Delete data** — any destructive or irreversible removal, including
   overwriting a file.
4. **Change settings** — any system, app, or account configuration change.

Read-only actions (lookups, reads, opens, queries) flow freely.

## Proactivity

**Yes — proactive, but quiet by default.** It earns the right to interrupt me;
it does not assume it. Most checks produce nothing most of the time. Anything
noteworthy that I wasn't present for is **held and shown to me on return** —
never delivered once and lost. Quiet hours are respected for non-urgent items.

## The rules that hold it together

1. **Get the brain working in plain text before adding a single line of audio.**
2. **One shared agent core, many ways in and out.** Typed, spoken, and
   heartbeat-initiated turns all flow through the same brain. Never fork the
   agent logic for voice.
3. **Work tier by tier.** Do not start a tier until the previous one runs and
   verifies on its own. Do not fuse tiers.
4. **The provider lives behind a thin seam.** Everything calls one function;
   nothing else touches the provider SDK.
5. **Extend the tool registry, never the core loop.**
6. **Treat everything read from the outside world as data, not commands.**
7. **Configuration over hardcoded values.**
8. **Secrets live in the environment or a git-ignored file — never in source.**

## Build order

| Tier | What | Status |
|---|---|---|
| 0 | Interview + this spec | ✅ done |
| 1 | The brain — text conversation loop | ✅ done |
| 2 | The hands — tool registry | ✅ done |
| 3 | The ears and mouth — push-to-talk voice | ✅ done |
| 4 | The memory — durable facts across restarts | ⬜ next |
| 5 | The heartbeat — proactive checks | ⬜ |
| 6 | The rails — confirmation gate, config, audit, kill switch | ⬜ |

## Tier 1 verification (what "done" means)

Run it, hold a short back-and-forth, and it clearly remembers earlier turns in
the same session. Kill it and restart → it has forgotten everything (expected;
memory is Tier 4). If a reply ever appears with no memory of the previous turn,
the history list is not being passed back in.

## Tier 2 verification (what "done" means)

Ask for something that needs a tool and watch the assistant call it, get a
result, and weave it into a natural reply. Then make the tool fail on purpose
and confirm the assistant explains the problem instead of crashing.

## The tool registry

15 tools across the first three capabilities. Adding a capability is one
self-contained module plus one line in `jarvis/tools/__init__.py` — the core
loop never changes.

| Module | Tools | Notes |
|---|---|---|
| `clock` | `get_current_time` | Safe, no network. |
| `weather` | `get_weather` | Open-Meteo, no key needed. |
| `notes` | `list_notes`, `read_note`, `create_note`, `append_note`, `delete_note` | Plain markdown in `state/notes/`. `delete_note` is consequential. |
| `apps` | `open_app`, `open_path`, `open_url` | Launches via argv lists, never a shell. |
| `messages` | `list_messages`, `read_message`, `draft_message`, `list_drafts`, `send_message` | Local store in `state/messages.json`. `send_message` is consequential. |

**Messaging is honest about its scope:** it is backed by a local store, not a
live mail or SMS account. The capability is real and testable now; wiring it to
a real provider is a credentials task later, and the tool shape will not change.

### Rules the registry enforces

- A tool failure returns a plain-language error **to the model**, which then
  decides how to explain it. The loop never crashes on a bad tool call.
- Tool descriptions are written for a reader, and inputs are typed and validated.
- Consequential tools (send, spend, delete, change settings) are flagged and
  **fail closed** until Tier 6 builds the real confirmation gate.

## Tier 3 verification (what "done" means)

Hold the key, ask a question that needs a tool, release, and hear a spoken
answer that used the tool — with the transcript visible so you can confirm it
heard you correctly. Start a new turn mid-reply and it stops to listen. The
typed interface still works exactly as it did in Tier 2.

## The voice layer

Voice is an adapter on the edges of the brain, never a fork of it. A spoken turn
is transcribed to text and handed to `Brain.ask` — the same entry point a typed
turn uses. Nothing in `jarvis/voice/` re-implements the agent.

| Piece | Providers | Notes |
|---|---|---|
| Ears (`stt`) | `whisper` (local, default), `deepgram` (cloud) | Whisper needs no key and runs offline. |
| Mouth (`tts`) | `espeak` (local, default), `elevenlabs` (cloud) | espeak is robotic but instant and free. |

**Both default to local**, so the entire voice loop works today with no signups
and no cost. Deepgram and ElevenLabs are wired and ready — add the key to `.env`
and change one line in `config.yaml` to switch either one.

### How a spoken turn flows

1. Hold **space**, speak, release. Push-to-talk means the start and end of a turn
   are never guessed at.
2. The recording is transcribed. What it *thought* you said is printed, always,
   so a wrong answer can be traced to the ears or the brain.
3. `(thinking…)` fires the instant you release the key, so silence never reads as
   "it broke".
4. The reply streams and is **spoken sentence by sentence** — the first sentence
   plays while the rest is still being written.
5. Press **Esc** while it is talking to cut it off. Holding space also interrupts
   and starts listening.

### Three decisions worth knowing

- **Local STT decodes audio itself.** faster-whisper's PyAV path passes a kwarg
  that recent PyAV versions removed, which breaks transcription outright. The
  harness decodes the WAV with the standard library and hands whisper a raw
  array — more robust, and faster, since audio is never decoded twice.
- **A tapped key is not speech.** Recordings under ~2 KB are discarded rather
  than sent to the transcriber as silence.
- **It cannot hear itself.** The microphone is only live while the key is held,
  and speech is stopped before capture begins. Push-to-talk sidesteps the
  self-listening problem entirely; this matters before any move to an open mic.

### Debugging voice without a microphone

```bash
.venv/bin/python -m jarvis --say "test the mouth"          # speak, no mic
.venv/bin/python -m jarvis --hear recording.wav            # transcribe a file
.venv/bin/python -m jarvis --voice-file recording.wav      # one full spoken turn
.venv/bin/python -m jarvis --voice                          # the real thing
```
