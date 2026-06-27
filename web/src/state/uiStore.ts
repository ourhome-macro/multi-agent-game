import { create } from "zustand";

export type Selection =
  | { kind: "hotspot"; id: string }
  | { kind: "character"; id: string }
  | { kind: "none"; id: null };

type UiStore = {
  currentSceneId: string | null;
  hoveredId: string | null;
  playerX: number;
  playerTargetX: number;
  selection: Selection;
  activePanel: "case" | "evidence" | "relations" | "events";
  setCurrentSceneId: (sceneId: string) => void;
  setHoveredId: (id: string | null) => void;
  setPlayerX: (x: number) => void;
  setPlayerTargetX: (x: number) => void;
  selectHotspot: (id: string) => void;
  selectCharacter: (id: string) => void;
  clearSelection: () => void;
  setActivePanel: (panel: UiStore["activePanel"]) => void;
};

export const useUiStore = create<UiStore>((set) => ({
  currentSceneId: null,
  hoveredId: null,
  playerX: -3.15,
  playerTargetX: -3.15,
  selection: { kind: "none", id: null },
  activePanel: "case",
  setCurrentSceneId: (sceneId) =>
    set({
      currentSceneId: sceneId,
      playerX: -3.15,
      playerTargetX: -3.15,
      selection: { kind: "none", id: null },
    }),
  setHoveredId: (id) => set({ hoveredId: id }),
  setPlayerX: (x) => set({ playerX: x }),
  setPlayerTargetX: (x) => set({ playerTargetX: x }),
  selectHotspot: (id) => set({ selection: { kind: "hotspot", id } }),
  selectCharacter: (id) => set({ selection: { kind: "character", id } }),
  clearSelection: () => set({ selection: { kind: "none", id: null } }),
  setActivePanel: (panel) => set({ activePanel: panel }),
}));
