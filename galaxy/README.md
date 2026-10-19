# jarvis-galaxy

A living galaxy for JARVIS: a wireframe orb floating in deep space, surrounded by
a slowly turning network of glowing star clusters.

Built from Trillion's *"Give Your AI a Face"* prompt, layer by layer, each layer
verified on screen before the next begins.

## Run it

```bash
npm install
npm run dev        # dev server
npm run build      # production build into dist/
npm test           # the pure maths, no GPU needed
```

## Structure

```
src/engine/
  state.ts        every visual parameter for every state, in one table
  easing.ts       frame-rate independent smoothing
  audio.ts        frequency bins -> voice/bass/treble, plus a synthetic fallback
  orb.ts          the orb, glow shell and rings (draws only)
  network/        star network generation (pure) + scene object (draws only)
  agents/         the sub-agent constellation
    spec.ts         orbit maths and the agent roster (pure, tested)
    avatar.ts       generated avatars — halo, disc, rim, initial
    constellation.ts  the orbiting avatars, beams, pings, docking
  labels.ts       HTML labels that follow the agents on screen
  index.ts        one renderer, one context, the frame loop
  shaders/        GLSL: simplex noise, the orb, the glow shell
src/demo/
  main.ts         the demo page: state buttons, agent controls, toggles
  bridge.ts       the JARVIS event bridge + window.galaxy console API
  panels.ts       one panel per agent — the docking targets
  labels.css      label and panel styling
tests/            unit tests for the pure modules
```

## The sub-agent constellation

Three agents orbit the orb, each on its own tilted path, with an HTML label that
tracks it on screen and fades as it swings behind the orb.

| Agent | Specialty | Docks beside |
|---|---|---|
| Scout | Hunts competitor and product news | `#panel-scout` |
| Board | Convenes the advisors | `#panel-board` |
| Mind | Maps memories and tools | `#panel-mindmap` |

Each agent reacts to real JARVIS activity:

- **Dispatch** — a beam races from the orb out to the agent and back, the agent
  flares, and a sonar ring expands at the peak.
- **Working** — a steady pulsing halo, and the agent leaves orbit to settle
  beside its panel, returning when the task finishes (fast in, slow out).
- **Thinking** — ripple waves expand from the orb while it processes.

Docking is computed by unprojecting the panel's real screen position, so the
agent lands beside the panel the user can actually see — not at a hard-coded
coordinate. An agent with no matching panel simply pulses in orbit.

## Driving it

JARVIS writes three files to `state/`, which the galaxy polls over HTTP:

| File | Carries |
|---|---|
| `galaxy-state.json` | the orb's conversational state |
| `galaxy-audio.json` | voice / bass / treble levels |
| `galaxy-events.json` | agent events: dispatch, working, add-agent |

Everything is also exposed on `window.galaxy` for testing from the console:

```js
galaxy.state("listening")
galaxy.dispatch("scout")
galaxy.working("board", true)
galaxy.agents()            // ["scout", "board", "mindmap"]
galaxy.addAgent({ ... })   // grows the constellation at runtime
```

Adding a fourth agent needs no art: give it an id, a name, a colour and orbit
parameters, and its avatar is generated on the fly.

## The discipline

The maths is pure and tested; the three.js code only draws numbers it is handed.
That is what lets the behaviour be verified without a GPU — and what made the two
bugs below findable.

## Layers

| Layer | What | Status |
|---|---|---|
| 1 | The orb — wireframe icosahedron, noise displacement, fresnel, glow shell, rings | ✅ done |
| 2 | The sky — nebula, stars, bloom | ✅ done |
| 3 | The star network — clusters, connections, dust | ✅ done |
| 4 | States and voice — real audio taps | ✅ done |
| 5 | Themes, performance, accessibility | ✅ done |
| 6 | The sub-agent constellation — orbiting avatars, labels, dispatch, docking | ✅ done |
| 7 | Wiring — real JARVIS events, console API, runtime agents | ✅ done |

## Two bugs worth remembering

Both were invisible in the code and obvious on screen — which is the argument for
capturing a real render at every layer rather than trusting that it looks right.

1. **`WireframeGeometry` carries no `normal` attribute.** The shader read
   `normal`, so every vertex got zero: the mesh collapsed and nothing was drawn.
   The normal is now derived from `position`, which is correct for a sphere.

2. **A rim term cannot come from the view vector alone.** With the camera 4.2
   units from a radius-1 sphere the view direction is nearly constant across the
   surface, so the fresnel was ~0 everywhere and the glow rendered as a filled
   disc. The normal is now carried to the fragment stage in view space.

## A fourth bug: a signed hash makes half the phases negative

`phaseFromId` hashed an agent id with `| 0`, which yields a *signed* 32-bit int.
`hash % 1000` then went negative for any id whose hash had the high bit set, so
half of all agents would have started at a negative orbit angle — orbiting
backwards, out of step with the rest. The unit test caught it; the fix is
`(hash >>> 0) % 1000`. Worth remembering because a hashed phase is the kind of
thing that looks fine on screen until the *one* agent you added does not.

## A footgun worth naming

`pkill -f "http.server 8791"` kills **itself** when the pattern appears in the
invoking shell's own command line — `pkill -f` matches the full command line of
every process, including the one running it. Kill by PID instead.

## A third bug: stars that paint their cell

A star field built on a hashed grid will show the grid if the star's glow is too
soft. The falloff `size / (d * density * 0.06 + size)` reached the cell boundary,
so every starred cell painted a soft square edge and the lattice became visible
across the whole sky. The hash was fine; the falloff was wrong. A star is a
point, so the glow now dies well inside its cell.
