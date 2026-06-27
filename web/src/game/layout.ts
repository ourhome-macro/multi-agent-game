import type { PublicCaseDetail, PublicCharacter, PublicScene } from "../types/public-api";

export type Vec3 = [number, number, number];

export type HotspotPlacement = {
  id: string;
  position: Vec3;
  size: Vec3;
  tone: "wine" | "brass" | "paper" | "medicine" | "power" | "stone";
};

export type CharacterPlacement = {
  id: string;
  position: Vec3;
  accent: string;
};

export type ScenePresentation = {
  hotspots: HotspotPlacement[];
  characters: CharacterPlacement[];
};

const fixedHotspots: Record<string, Record<string, Omit<HotspotPlacement, "id">>> = {
  study: {
    wine_table: { position: [-2.55, 0.2, -0.95], size: [1.05, 0.28, 0.78], tone: "wine" },
    study_lock: { position: [3.05, 0.75, -1.45], size: [0.46, 1.35, 0.18], tone: "brass" },
    tape_recorder: { position: [-0.6, 0.33, -1.68], size: [0.85, 0.26, 0.48], tone: "brass" },
    burned_letter: { position: [2.18, 0.28, 0.96], size: [0.92, 0.18, 0.52], tone: "paper" },
    medicine_box: { position: [0.78, 0.3, -0.58], size: [0.74, 0.22, 0.44], tone: "medicine" },
    breaker_box: { position: [-3.2, 0.88, 1.15], size: [0.44, 1.0, 0.22], tone: "power" },
    desk_embossed_pages: { position: [0.18, 0.42, -1.08], size: [0.78, 0.08, 0.5], tone: "paper" },
    medicine_drawer_liner: { position: [1.32, 0.24, -0.18], size: [0.72, 0.08, 0.42], tone: "medicine" },
    editing_lamp: { position: [-1.05, 0.56, -1.28], size: [0.38, 0.64, 0.38], tone: "brass" },
    pocket_watch: { position: [0.28, 0.36, -1.72], size: [0.38, 0.08, 0.38], tone: "brass" },
  },
  clock_tower: {
    tower_backup_line: { position: [-1.78, 0.68, -1.1], size: [0.82, 1.12, 0.26], tone: "power" },
    tower_clockwork: { position: [1.25, 1.08, -0.65], size: [1.45, 1.45, 0.35], tone: "brass" },
  },
  gallery: {
    covered_frame: { position: [-2.12, 1.02, -1.42], size: [1.28, 1.12, 0.16], tone: "paper" },
    archive_case: { position: [0.62, 0.35, -1.28], size: [1.35, 0.54, 0.42], tone: "brass" },
    side_door_carpet: { position: [2.45, 0.12, 0.82], size: [1.2, 0.08, 0.72], tone: "stone" },
  },
};

const fixedCharacters: Record<string, Record<string, Vec3>> = {
  study: {
    lin_qichi: [-2.2, 0.5, 1.18],
    qi_yan: [0, 0.5, 1.32],
    jiang_yanhui: [2.18, 0.5, 1.1],
  },
  clock_tower: {
    shen_zhaoye: [0.8, 0.5, 1.2],
  },
  gallery: {
    lin_qichi: [-1.42, 0.5, 1.08],
    qi_yan: [1.45, 0.5, 1.08],
  },
};

const characterAccents = ["#b25f5f", "#d0a04f", "#73946f", "#7d91aa", "#a5729a"];

export function buildScenePresentation(
  scene: PublicScene,
  caseDetail: PublicCaseDetail,
): ScenePresentation {
  const hotspotHints = fixedHotspots[scene.id] || {};
  const characterHints = fixedCharacters[scene.id] || {};
  const hotspots = scene.hotspots.map((hotspot, index) => ({
    id: hotspot.id,
    ...(hotspotHints[hotspot.id] || fallbackHotspot(scene.hotspots.length, index, hotspot.id)),
  }));

  const characters = scene.characters.map((characterId, index) => {
    const character = caseDetail.characters.find((item) => item.id === characterId);
    return {
      id: characterId,
      position: characterHints[characterId] || fallbackCharacter(scene.characters.length, index),
      accent: accentForCharacter(character, index),
    };
  });

  return { hotspots, characters };
}

function fallbackHotspot(
  total: number,
  index: number,
  id: string,
): Omit<HotspotPlacement, "id"> {
  const angle = (Math.PI * 2 * index) / Math.max(1, total) - Math.PI / 2;
  const radius = 1.9 + (hash(id) % 5) * 0.12;
  const tone: HotspotPlacement["tone"][] = ["brass", "paper", "stone", "wine", "medicine"];
  return {
    position: [Math.cos(angle) * radius, 0.22, Math.sin(angle) * radius * 0.68],
    size: [0.82, 0.18, 0.52],
    tone: tone[hash(id) % tone.length],
  };
}

function fallbackCharacter(total: number, index: number): Vec3 {
  const step = 3 / Math.max(1, total - 1 || 1);
  return [-1.5 + step * index, 0.5, 1.24];
}

function accentForCharacter(character: PublicCharacter | undefined, index: number): string {
  if (!character) return characterAccents[index % characterAccents.length];
  return characterAccents[hash(character.id) % characterAccents.length];
}

function hash(value: string): number {
  let result = 0;
  for (let index = 0; index < value.length; index += 1) {
    result = (result * 31 + value.charCodeAt(index)) >>> 0;
  }
  return result;
}
