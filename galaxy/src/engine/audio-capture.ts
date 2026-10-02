/**
 * Real audio capture.
 *
 * Uses Web Audio API's AnalyserNode to get real frequency data from the
 * microphone and/or playback. Falls back to synthetic levels when no audio
 * source is available, so the orb always has something to react to.
 *
 * The analyserNode is configured for 2048 frequency bins, which gives good
 * resolution across the speech band. The audio.ts module reads those bins
 * and turns them into the three levels the orb needs.
 */

import { readLevels, syntheticLevels, ZERO_LEVELS, type AudioLevels } from "./audio";

export interface AudioCaptureOptions {
  /** FFT size for the analyser. 2048 gives good speech-band resolution. */
  fftSize?: number;
  /** Smoothing time constant for the analyser. */
  smoothing?: number;
}

export class AudioCapture {
  private ctx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private micStream: MediaStream | null = null;
  private micSource: MediaStreamAudioSourceNode | null = null;
  private playbackSource: MediaElementAudioSourceNode | null = null;
  private bins: Float32Array<ArrayBuffer> = new Float32Array(0);
  private levels: AudioLevels = ZERO_LEVELS;
  private elapsed = 0;
  private usingRealAudio = false;

  /**
   * Start capturing audio.
   *
   * Tries microphone first, then playback audio. If neither is available,
   * falls back to synthetic levels so the orb still breathes.
   */
  async start(opts: AudioCaptureOptions = {}): Promise<void> {
    const { fftSize = 2048, smoothing = 0.8 } = opts;

    try {
      this.ctx = new AudioContext();
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = fftSize;
      this.analyser.smoothingTimeConstant = smoothing;
      this.bins = new Float32Array(this.analyser.frequencyBinCount);

      // Try microphone first.
      try {
        this.micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        this.micSource = this.ctx.createMediaStreamSource(this.micStream);
        this.micSource.connect(this.analyser);
        this.usingRealAudio = true;
        return;
      } catch {
        // Mic denied or unavailable — try playback audio.
      }

      // Try playback audio (e.g. an <audio> or <video> element on the page).
      const media = document.querySelector("audio, video") as HTMLMediaElement | null;
      if (media) {
        this.playbackSource = this.ctx.createMediaElementSource(media);
        this.playbackSource.connect(this.analyser);
        this.analyser.connect(this.ctx.destination);
        this.usingRealAudio = true;
        return;
      }

      // No real audio available — use synthetic.
      this.usingRealAudio = false;
    } catch {
      // Web Audio not available at all — fall back to synthetic.
      this.usingRealAudio = false;
    }
  }

  /**
   * Read the current audio levels.
   *
   * If real audio is available, reads from the analyser. Otherwise generates
   * synthetic levels based on whether the AI is speaking.
   */
  read(delta: number, speaking: boolean): AudioLevels {
    this.elapsed += delta;

    if (this.usingRealAudio && this.analyser) {
      this.analyser.getFloatFrequencyData(this.bins);
      const raw = readLevels(this.bins, { mic: !!this.micSource });
      // Smooth the levels so the orb doesn't twitch.
      this.levels = {
        voice: this.levels.voice + (raw.voice - this.levels.voice) * 0.45,
        bass: this.levels.bass + (raw.bass - this.levels.bass) * 0.45,
        treble: this.levels.treble + (raw.treble - this.levels.treble) * 0.45,
      };
      return this.levels;
    }

    // Synthetic fallback.
    const raw = syntheticLevels(this.elapsed, speaking);
    this.levels = {
      voice: this.levels.voice + (raw.voice - this.levels.voice) * 0.3,
      bass: this.levels.bass + (raw.bass - this.levels.bass) * 0.3,
      treble: this.levels.treble + (raw.treble - this.levels.treble) * 0.3,
    };
    return this.levels;
  }

  /** Whether real audio is being captured (vs synthetic fallback). */
  get isUsingRealAudio(): boolean {
    return this.usingRealAudio;
  }

  /** Stop capturing and release resources. */
  stop(): void {
    this.micStream?.getTracks().forEach((t) => t.stop());
    this.micStream = null;
    this.micSource?.disconnect();
    this.micSource = null;
    this.playbackSource?.disconnect();
    this.playbackSource = null;
    this.analyser?.disconnect();
    this.analyser = null;
    this.ctx?.close();
    this.ctx = null;
    this.usingRealAudio = false;
  }
}
