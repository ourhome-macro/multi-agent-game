import { useCallback, useState } from "react";

import { soundEngine } from "./SoundEngine";

export function useSound() {
  const [enabled, setEnabledState] = useState(true);
  const [volume, setVolumeState] = useState(0.55);

  const setEnabled = useCallback((next: boolean) => {
    soundEngine.setEnabled(next);
    setEnabledState(next);
  }, []);

  const setVolume = useCallback((next: number) => {
    soundEngine.setVolume(next);
    setVolumeState(next);
  }, []);

  return {
    enabled,
    volume,
    setEnabled,
    setVolume,
    play: soundEngine.play.bind(soundEngine),
  };
}
