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
