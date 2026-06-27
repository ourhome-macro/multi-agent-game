import { create } from "zustand";

import type { ActorMotionState } from "../game/actorState";

export type MovementVector = { x: number; y: number };

export type Selection =
  | { kind: "hotspot"; id: string }
  | { kind: "character"; id: string }
  | { kind: "none"; id: null };

type UiStore = {
  currentSceneId: string | null;
  hoveredId: string | null;
  playerX: number;
  playerY: number;
  playerTargetX: number;
  playerTargetY: number;
  playerMotion: ActorMotionState;
  keyboardVector: MovementVector;
  selection: Selection;
  activePanel: "story" | "case" | "evidence";
  setCurrentSceneId: (sceneId: string) => void;
  setHoveredId: (id: string | null) => void;
  setPlayerPosition: (x: number, y: number) => void;
  setPlayerTarget: (x: number, y: number) => void;
  setPlayerMotion: (motion: ActorMotionState) => void;
  setKeyboardVector: (vector: MovementVector) => void;
  selectHotspot: (id: string) => void;
  selectCharacter: (id: string) => void;
  clearSelection: () => void;
  setActivePanel: (panel: UiStore["activePanel"]) => void;
};

const playerSpawn = { x: -3.15, y: -1.08 };

export const useUiStore = create<UiStore>((set) => ({
  currentSceneId: null,
  hoveredId: null,
  playerX: playerSpawn.x,
  playerY: playerSpawn.y,
  playerTargetX: playerSpawn.x,
  playerTargetY: playerSpawn.y,
  playerMotion: "idle",
  keyboardVector: { x: 0, y: 0 },
  selection: { kind: "none", id: null },
  activePanel: "story",
  setCurrentSceneId: (sceneId) =>
    set({
      currentSceneId: sceneId,
      playerX: playerSpawn.x,
      playerY: playerSpawn.y,
      playerTargetX: playerSpawn.x,
      playerTargetY: playerSpawn.y,
      keyboardVector: { x: 0, y: 0 },
      selection: { kind: "none", id: null },
    }),
  setHoveredId: (id) => set({ hoveredId: id }),
  setPlayerPosition: (x, y) => set({ playerX: x, playerY: y }),
  setPlayerTarget: (x, y) => set({ playerTargetX: x, playerTargetY: y }),
  setPlayerMotion: (motion) => set({ playerMotion: motion }),
  setKeyboardVector: (vector) => set({ keyboardVector: vector }),
  selectHotspot: (id) => set({ selection: { kind: "hotspot", id } }),
  selectCharacter: (id) => set({ selection: { kind: "character", id } }),
  clearSelection: () => set({ selection: { kind: "none", id: null } }),
  setActivePanel: (panel) => set({ activePanel: panel }),
}));
