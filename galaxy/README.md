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
  index.ts        one renderer, one context, the frame loop
  shaders/        GLSL: simplex noise, the orb, the glow shell
src/demo/         the demo page: state buttons and toggles
tests/            unit tests for the pure modules
```

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
| 4 | States and voice — real audio taps | ⬜ (table and synthetic path done) |
| 5 | Themes, performance, accessibility | ⬜ (perf + reduced motion done) |

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
