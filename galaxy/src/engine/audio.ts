/**
 * Audio levels.
 *
 * Pure maths, no WebGL and no Web Audio — the analyser hands us a Float32Array
 * of frequency bins and this turns it into the three numbers the orb needs. That
 * separation is what makes it testable.
 *
 * The bands are fractions of the spectrum rather than fixed bin indices, so the
 * same code works whether the analyser is configured for 512 bins or 2048.
 */

/** Which slice of the spectrum each band covers, as a fraction of bin count. */
const VOICE_FROM = 0.1;
const VOICE_TO = 0.6;
const BASS_BINS = 6;
const TREBLE_FROM = 0.65;

export interface AudioLevels {
  /** Average energy across the speech band. Drives displacement. */
  voice: number;
  /** Low-frequency energy. Drives the swell and the network. */
  bass: number;
  /** High-frequency energy. Switches on the finest noise octave. */
  treble: number;
}

export const ZERO_LEVELS: AudioLevels = { voice: 0, bass: 0, treble: 0 };

/**
 * Smoothing envelope.
 *
 * Fast attack, slow decay. Without this the orb twitches on every frame;
 * with it, it breathes. The asymmetry is the point — sound should register
 * immediately and fade away gently, like a real meter.
 */
export const ATTACK = 0.45;
export const DECAY = 0.08;

/** Microphone input is quieter than playback, so it gets a lift and a floor. */
export const MIC_GAIN = 2.4;
export const MIC_FLOOR = 0.06;

/**
 * Read one band's average from a frequency spectrum.
 *
 * `bins` is whatever `AnalyserNode.getFloatFrequencyData` produced. Values are
 * typically in decibels and negative, so they are normalised into 0..1 here
 * rather than leaking that detail into the renderer.
 */
export function bandAverage(
  bins: ArrayLike<number>,
  fromFraction: number,
  toFraction: number,
): number {
  const n = bins.length;
  if (n === 0) return 0;

  const from = Math.max(0, Math.min(n - 1, Math.floor(n * fromFraction)));
  const to = Math.max(from + 1, Math.min(n, Math.ceil(n * toFraction)));

  let sum = 0;
  for (let i = from; i < to; i++) sum += bins[i];
  const mean = sum / (to - from);

  // dBFS is roughly -100 (silence) to 0 (full scale). Map that to 0..1.
  const normalised = (mean + 100) / 100;
  return normalised < 0 ? 0 : normalised > 1 ? 1 : normalised;
}

/** Turn a spectrum into the three levels the scene uses. */
export function readLevels(
  bins: ArrayLike<number>,
  opts: { mic?: boolean } = {},
): AudioLevels {
  const voice = bandAverage(bins, VOICE_FROM, VOICE_TO);
  const bass = bandAverage(bins, 0, BASS_BINS / Math.max(1, bins.length));
  const treble = bandAverage(bins, TREBLE_FROM, 1);

  if (!opts.mic) return { voice, bass, treble };

  // The mic never fully drops out, so the orb does not look dead between
  // syllables.
  return {
    voice: Math.min(1, voice * MIC_GAIN + MIC_FLOOR),
    bass: Math.min(1, bass * MIC_GAIN + MIC_FLOOR),
    treble,
  };
}

/** Apply the attack/decay envelope to a new reading. */
export function smoothLevel(previous: number, next: number): number {
  const rate = next > previous ? ATTACK : DECAY;
  return previous + (next - previous) * rate;
}

export function smoothLevels(previous: AudioLevels, next: AudioLevels): AudioLevels {
  return {
    voice: smoothLevel(previous.voice, next.voice),
    bass: smoothLevel(previous.bass, next.bass),
    treble: smoothLevel(previous.treble, next.treble),
  };
}

/**
 * A deterministic stand-in for real audio.
 *
 * Used when no analyser is available, so the scene still reads as alive on a
 * machine with no microphone and in tests. Deterministic on purpose: the same
 * elapsed time always yields the same levels, which keeps visual tests stable.
 */
export function syntheticLevels(elapsed: number, speaking: boolean): AudioLevels {
  if (!speaking) {
    return { voice: 0, bass: 0, treble: 0 };
  }
  // Two incommensurable rates so the pattern does not visibly repeat, plus a
  // syllabic wobble that reads like speech rather than a tone.
  const syllable = 0.5 + 0.5 * Math.sin(elapsed * 7.3);
  const phrase = 0.55 + 0.45 * Math.sin(elapsed * 1.7 + 1.1);
  const breath = 0.5 + 0.5 * Math.sin(elapsed * 0.9);

  const voice = Math.max(0, syllable * phrase) * 0.85;
  const bass = Math.max(0, phrase * breath) * 0.7;
  const treble = Math.max(0, syllable * 0.6) * 0.5;
  return { voice, bass, treble };
}

/**
 * The vertex displacement for the orb.
 *
 * Kept here, not in the shader, so the shape can be tested without a GPU. The
 * shader receives the final number.
 *
 * The key insight from the spec: the noise is multiplied by how much is going
 * on. At rest the orb barely ripples, and it is the audio that makes it move —
 * not a constant animation.
 */
export function displacement(
  base: number,
  breath: number,
  levels: AudioLevels,
  amplitude: number,
): number {
  const fromAudio = levels.voice * amplitude * 0.55;
  const fromBass = levels.bass * amplitude * 0.35;
  const total = base + breath + fromAudio + fromBass;
  return Math.max(-0.45, Math.min(0.45, total));
}

/** The slow breath that keeps the orb alive when nothing else is happening. */
export function breathValue(elapsed: number): number {
  return Math.sin(elapsed * 0.7) * 0.04;
}
