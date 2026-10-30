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

## Ways to talk to him

| Mode | Command | In → Out |
|---|---|---|
| Voice (default) | `./jarvis` | speak → hear |
| Wake word | `./jarvis-wake` | say "jarvis" → speak → hear |
| Text | `./jarvis --text` | type → read |
| **Speak** | `./jarvis-speak` or `./jarvis --speak` | **type → read *and* hear** |

### Wake word

```bash
./jarvis-wake
```

Say **"hey jarvis"**, then speak your request. No key to hold.

**Say "hey jarvis" — not "jarvis".** The model is trained on the full phrase;
plain "jarvis" scores ~0.09 and will never wake him. This is the single most
common reason it appears not to work.

**This needs no account and no API key.** It runs openWakeWord, which is fully
open source: the model runs on your CPU through onnxruntime, so nothing leaves
the machine and there is nothing to sign up for. (Porcupine is also supported —
see below.)

Two things it does need:

1. **A microphone.** Any ALSA capture device works; `arecord -l` lists yours.
   Speak close to it — a laptop mic at arm's length scores noticeably worse
   than one a few inches away.
2. **The wake word model.** openWakeWord's pretrained models are not in the pip
   package — they are fetched from its GitHub releases on first run. If that
   download has not happened yet:
   ```bash
   .venv/bin/python -m jarvis.tools.fetch_wake_models
   ```

The `hey_jarvis` keyword ships with openWakeWord, which is the name this project
always intended.

After the wake word it records until you stop talking — silence is detected by
energy, so talk, pause about a second and a half, and the turn is sent. That is
deliberately crude next to a real voice-activity detector, but it needs nothing
extra and behaves the way you'd expect.

Sensitivity is `voice.wake_sensitivity` in `config.yaml`. Measured on real
speech, "hey jarvis" reaches ~0.5–0.9 while ordinary sentences stay under 0.1,
so 0.4 sits safely between them. Raise it if he misses you, lower it if he wakes
at the television. Set `wake_word:` to empty to disable the mode entirely.

#### Not waking? Diagnose it

```bash
.venv/bin/python -m jarvis.tools.wake_debug --seconds 30
```

This prints the live mic level and the model's score per frame, so you can tell
the two failure modes apart: if the level stays near zero the mic isn't hearing
you, if the score stays low the phrase or the distance is the problem.

#### Switching to Porcupine

Porcupine is purpose-built for this and cheaper on CPU, but its free key asks
for a company email. If you ever get one, put it in `.env` as
`PORCUPINE_ACCESS_KEY` and wake mode uses it automatically — no other change
needed. Note Porcupine's keyword is plain `jarvis`, so if you switch engines,
change `wake_word` back to `jarvis` too.

### Speak mode

Speak mode is the one for reading along while he talks: every reply is printed
*and* read aloud in his own voice. Press **Enter** during a reply to skip the
rest of it, and `/speak off` to silence him without leaving the session.

```bash
./jarvis-speak                 # interactive
./jarvis --speak -m "hi"       # one shot, still spoken
```

The reply is spoken as a whole once it is finished, not word by word — a
streamed answer read aloud as it arrives sounds broken. Text typed while he is
speaking is kept and becomes your next message rather than being lost.

**A provider that is configured is not a provider that works.** An API key runs
out of quota mid-month and a free service changes its endpoint without notice, so
the voice layer keeps a fallback chain: `edge` → `piper` → `espeak`. The first
sentence that the configured provider cannot speak moves to the next one for the
rest of the session, and **the switch is announced** — silently hearing a
different voice reads as a bug. `tts.providers` in `config.yaml` holds each
provider's own voice and rate, so a fallback uses the voice you picked for it
rather than a default.

`piper` is free, offline and neural, and needs no key — it is the safest voice
to fall back to. `espeak` is last because it is robotic, but it needs nothing at
all: no key, no network, no model.

## Design rules

1. Brain works in plain text before any audio exists.
2. One agent core, many ways in and out — never fork the logic for voice.
3. Extend the tool registry, never the core loop.
4. Secrets live in the environment, never in source.

## Business status report

JARVIS can read the business's websites and YouTube channels and report on them:

```bash
.venv/bin/python -m jarvis --status-report
```

It reports whether each site is up, which pages are broken, every channel's
recent uploads and cadence, and anything that looks wrong — and it runs
quietly in the background via the `presence` heartbeat check, speaking only
when something changes (a site goes down, a new video lands, a page breaks, a
channel goes quiet).

A business can run more than one brand, so targets are **lists**. They live in
`config.yaml` under `presence:`:

```yaml
presence:
  websites:
    - https://minuro.vercel.app/
    - https://second-brand.example.com      # add another line per site
  youtube_channels:
    - https://www.youtube.com/@MINUROStudio
    - https://www.youtube.com/@SecondChannel
```

The singular `website_url` / `youtube_channel` fields are still honoured and
merged into the lists, so an older config keeps working unchanged.

YouTube is read from each channel's **public RSS feed** — no API key, nothing
to revoke. Handles are resolved to a channel id once and cached. Three tools
are also registered (`check_website`, `check_youtube_channel`,
`business_status_report`) so JARVIS can answer the question conversationally.

Each target is tracked separately, so a second brand cannot hide behind the
first one staying healthy — if one site is down, that is what gets reported.

### Analytics

`--status-report` is a snapshot. For trends there is:

```bash
.venv/bin/python -m jarvis --analytics
```

It reports whether total views are growing, which videos gained the most and
how fast, how often the channel is uploading, and each website's uptime
percentage. History is stored in `state/presence-history.db` (SQLite) and
appended by the heartbeat check each day, so trends appear after a few days.
`record_presence` stores a snapshot on demand if you want to build history
faster.

### Traffic per day

`--analytics` says whether the total is moving. For how much arrived on each
individual day:

```bash
.venv/bin/python -m jarvis --daily
```

It reports the channel's views per day — the total, the daily average, the
busiest and slowest day, a day-by-day series, and each video's views-per-day
rate. The arithmetic lives in `jarvis/presence/daily.py`, kept free of SQL so it
is directly testable.

Two honest limits, both stated in the output rather than papered over:

* **Views, not people.** YouTube's feed counts views, so a day with 3 views may
  be 3 people or one person watching three times. The feed cannot say.
* **Websites need a traffic source.** A site with no analytics snippet has no
  visitor count to read, and the report says so instead of printing zero — a
  zero reads as "nobody visited" when the truth is "nobody counted".

A day of traffic needs two snapshots, so the first snapshot after a gap
establishes the baseline rather than a day. `history.channel_video_views`
includes the last snapshot *before* the window for exactly that reason.

### Graph sheet

For the same trends as charts:

```bash
.venv/bin/python -m jarvis --graph-sheet
```

This writes `reports/presence-graph-sheet.html` — a single self-contained page
with inline SVG charts and **no external requests**, so it opens offline on any
device and can be archived. It draws, for every target:

| Section | Charts |
|---|---|
| YouTube | total views over time · views by video |
| Websites | response time · page size |

The per-video chart is the one that matters: it shows *which* video is working,
not just whether the channel total moved. That is only possible because history
stores per-video views rather than a channel total.

Websites also record **response time, page size, word count, and SSL expiry** —
the metrics a site owner can actually act on, and all trendable.

