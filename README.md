# JARVIS

A voice-first personal assistant. Built tier by tier — see **AGENT.md** for the
spec, the decisions from the interview, and the build order.

**Current state: Tier 1 — the brain.** A text conversation loop that remembers
the session in memory. No tools, no audio, no long-term memory yet.

## Setup

```bash
cd ~/jarvis
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # then edit .env and add your key
```

The key lives in `.env`, which is git-ignored. It is never written into source.

## Run it

```bash
.venv/bin/python -m jarvis
```

Then type. `/reset` forgets the session, `/quit` exits.

Non-interactive, for scripted checks:

```bash
.venv/bin/python -m jarvis -m "my name is Mike" -m "what is my name?" --show-transcript
```

## On your phone

JARVIS ships as an installable web app (PWA) — no Play Store, no APK, no build
step. It reuses the same brain, tools, memory and session as the terminal.

```bash
./jarvis-mobile
```

It prints two things: a phone URL on your wifi (`http://<lan-ip>:8794/`) and a
pairing token. Open the URL on your phone, paste the token once, then use your
browser's **Add to Home Screen**. It installs with its own icon and opens
fullscreen like a native app.

The token is stored in `state/mobile-token.txt` and persists across restarts, so
you pair once. It exists because a LAN is not a private place — every API call
requires it, and the server refuses anything without it.

Voice input uses the phone's own speech recognition, so no audio ever leaves the
device. Consequential tools (send, spend, delete) surface an approval sheet on
the phone and block until you tap Approve or Decline; if nobody answers within
two minutes the action does not happen.

### A real APK, if you want one

The PWA above installs from the browser. If you would rather have a genuine
installable Android app, there is one:

```bash
./build-apk.sh          # → ~/jarvis/JARVIS.apk
adb install -r JARVIS.apk
```

It is built with the Android SDK tools directly — no Gradle, no Android Studio,
no network at build time — and comes out around 36 KB. See `android/README.md`
for how to install it without a cable and how to re-point it at a new IP.

The APK is a thin native shell around the same web app: all conversation logic,
tools and keys stay on the server. Only rebuild it when the shell changes; JARVIS
itself needs no rebuild.


## Swapping the brain

`config.yaml` decides which provider thinks. Two are wired:

| `brain.provider` | What it is | Needs |
|---|---|---|
| `gemini` | Gemini 3 Pro over the REST API (default) | `GEMINI_API_KEY` in `.env` |
| `ollama` | A local model, fully offline | `ollama serve` running |

Changing the model is a one-line edit in `config.yaml` — no code change. Every
provider sits behind one seam (`jarvis/providers/base.py`), so the rest of the
harness never knows which one is in use.

## Layout

```
jarvis/
  config.yaml            all tunables: name, tone, model, thresholds
  AGENT.md               the spec — single source of truth
  jarvis/
    config.py            loads config.yaml + .env
    prompts.py           the system prompt
    brain.py             the conversation loop
    cli.py               the text interface
    providers/
      base.py            the seam: Message, TextDelta, TurnEnd, ProviderError
      gemini.py          Gemini implementation
      ollama.py          local implementation
```

## Design rules

1. Brain works in plain text before any audio exists.
2. One agent core, many ways in and out — never fork the logic for voice.
3. Extend the tool registry, never the core loop.
4. Secrets live in the environment, never in source.
