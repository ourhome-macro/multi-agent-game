type SoundName = "hover" | "click" | "inspect" | "clue" | "dialogue" | "phase" | "error";

class SoundEngine {
  private context: AudioContext | null = null;
  private enabled = true;
  private volume = 0.55;
  private lastHoverAt = 0;

  setEnabled(enabled: boolean) {
    this.enabled = enabled;
  }

  setVolume(volume: number) {
    this.volume = Math.max(0, Math.min(1, volume));
  }

  async play(name: SoundName) {
    if (!this.enabled) return;
    const context = await this.ensureContext();
    if (!context) return;
    if (name === "hover") {
      const now = performance.now();
      if (now - this.lastHoverAt < 90) return;
      this.lastHoverAt = now;
    }

    if (name === "error") {
      this.tone(context, 160, 0.14, "sawtooth", 0.22);
      this.tone(context, 90, 0.18, "triangle", 0.12, 0.05);
      return;
    }

    if (name === "clue") {
      this.tone(context, 520, 0.12, "sine", 0.18);
      this.tone(context, 830, 0.18, "triangle", 0.14, 0.08);
      this.noise(context, 0.16, 0.05);
      return;
    }

    if (name === "phase") {
      this.tone(context, 220, 0.2, "triangle", 0.12);
      this.tone(context, 330, 0.24, "triangle", 0.12, 0.12);
      this.tone(context, 440, 0.28, "triangle", 0.12, 0.25);
      return;
    }

    const map: Record<Exclude<SoundName, "error" | "clue" | "phase">, number> = {
      hover: 420,
      click: 280,
      inspect: 190,
      dialogue: 360,
    };
    this.tone(context, map[name], name === "hover" ? 0.04 : 0.1, "triangle", 0.16);
  }

  private async ensureContext(): Promise<AudioContext | null> {
    if (!this.context) {
      const AudioCtor = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtor) return null;
      this.context = new AudioCtor();
    }
    if (this.context.state === "suspended") {
      await this.context.resume();
    }
    return this.context;
  }

  private tone(
    context: AudioContext,
    frequency: number,
    duration: number,
    type: OscillatorType,
    gainValue: number,
    offset = 0,
  ) {
    const start = context.currentTime + offset;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = type;
    oscillator.frequency.setValueAtTime(frequency, start);
    oscillator.frequency.exponentialRampToValueAtTime(Math.max(40, frequency * 0.82), start + duration);
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(gainValue * this.volume, start + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start(start);
    oscillator.stop(start + duration + 0.02);
  }

  private noise(context: AudioContext, duration: number, gainValue: number) {
    const buffer = context.createBuffer(1, context.sampleRate * duration, context.sampleRate);
    const data = buffer.getChannelData(0);
    for (let index = 0; index < data.length; index += 1) {
      data[index] = (Math.random() * 2 - 1) * (1 - index / data.length);
    }
    const source = context.createBufferSource();
    const gain = context.createGain();
    gain.gain.value = gainValue * this.volume;
    source.buffer = buffer;
    source.connect(gain);
    gain.connect(context.destination);
    source.start();
  }
}

declare global {
  interface Window {
    webkitAudioContext?: typeof AudioContext;
  }
}

export const soundEngine = new SoundEngine();
