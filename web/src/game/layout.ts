import type { PublicCaseDetail, PublicCharacter, PublicScene } from "../types/public-api";

export type Vec3 = [number, number, number];

export type HotspotPlacement = {
  id: string;
  position: Vec3;
  size: Vec3;
  tone: "wine" | "brass" | "paper" | "medicine" | "power" | "stone";
  travelX: number;
  travelY?: number;
};

export type CharacterPlacement = {
  id: string;
  position: Vec3;
  accent: string;
  travelX: number;
  travelY?: number;
};

export type ScenePortal = {
  id: string;
  label: string;
  description: string;
  toSceneId: string;
  position: Vec3;
  travelX: number;
  travelY?: number;
  direction: "up" | "down" | "side";
};

export type ScenePresentation = {
  hotspots: HotspotPlacement[];
  characters: CharacterPlacement[];
  portals: ScenePortal[];
};

const fixedHotspots: Record<string, Record<string, Omit<HotspotPlacement, "id">>> = {
  study: {
    wine_table: { position: [-3.2, -1.08, 0.1], size: [0.7, 0.46, 0.08], tone: "wine", travelX: -3.0 },
    study_lock: { position: [3.55, -0.42, 0.1], size: [0.42, 1.3, 0.08], tone: "brass", travelX: 3.05 },
    tape_recorder: { position: [-0.35, -0.82, 0.1], size: [0.84, 0.38, 0.08], tone: "brass", travelX: -0.55 },
    burned_letter: { position: [2.15, -0.72, 0.1], size: [0.78, 0.38, 0.08], tone: "paper", travelX: 1.85 },
    medicine_box: { position: [0.95, -0.92, 0.1], size: [0.58, 0.34, 0.08], tone: "medicine", travelX: 0.72 },
    breaker_box: { position: [-3.85, 0.18, 0.1], size: [0.44, 0.96, 0.08], tone: "power", travelX: -3.35 },
    desk_embossed_pages: { position: [0.12, -0.54, 0.1], size: [0.78, 0.18, 0.08], tone: "paper", travelX: -0.08 },
    medicine_drawer_liner: { position: [1.38, -1.02, 0.1], size: [0.62, 0.18, 0.08], tone: "medicine", travelX: 1.1 },
    editing_lamp: { position: [-0.98, -0.4, 0.1], size: [0.38, 0.7, 0.08], tone: "brass", travelX: -1.08 },
    pocket_watch: { position: [0.38, -0.64, 0.1], size: [0.32, 0.18, 0.08], tone: "brass", travelX: 0.18 },
  },
  clock_tower: {
    tower_backup_line: { position: [-2.35, -0.26, 0.1], size: [0.76, 1.02, 0.08], tone: "power", travelX: -2.1 },
    tower_clockwork: { position: [1.25, 0.15, 0.1], size: [1.42, 1.42, 0.08], tone: "brass", travelX: 1.0 },
  },
  gallery: {
    covered_frame: { position: [-2.42, 0.25, 0.1], size: [1.16, 0.98, 0.08], tone: "paper", travelX: -2.2 },
    archive_case: { position: [0.45, -0.92, 0.1], size: [1.22, 0.52, 0.08], tone: "brass", travelX: 0.25 },
    side_door_carpet: { position: [2.72, -1.34, 0.1], size: [1.18, 0.22, 0.08], tone: "stone", travelX: 2.35 },
  },
};

const fixedCharacters: Record<string, Record<string, Vec3>> = {
  study: {
    lin_qichi: [-2.15, -1.0, 0.2],
    qi_yan: [-0.05, -1.0, 0.2],
    jiang_yanhui: [2.35, -1.0, 0.2],
  },
  clock_tower: {
    shen_zhaoye: [0.85, -1.0, 0.2],
  },
  gallery: {
    lin_qichi: [-1.25, -1.0, 0.2],
    qi_yan: [1.25, -1.0, 0.2],
  },
};

const characterAccents = ["#b25f5f", "#d0a04f", "#73946f", "#7d91aa", "#a5729a"];

const scenePortals: Record<string, ScenePortal[]> = {
  study: [
    {
      id: "study_to_tower",
      label: "上楼",
      description: "沿北侧楼梯去钟楼",
      toSceneId: "clock_tower",
      position: [-4.15, -0.9, 0.18],
      travelX: -3.7,
      direction: "up",
    },
    {
      id: "study_to_gallery",
      label: "去画廊",
      description: "推开侧门进入长廊",
      toSceneId: "gallery",
      position: [4.15, -0.9, 0.18],
      travelX: 3.65,
      direction: "side",
    },
  ],
  clock_tower: [
    {
      id: "tower_to_study",
      label: "下楼",
      description: "沿湿滑木梯回到书房",
      toSceneId: "study",
      position: [-4.0, -0.9, 0.18],
      travelX: -3.55,
      direction: "down",
    },
  ],
  gallery: [
    {
      id: "gallery_to_study",
      label: "回书房",
      description: "穿过侧门回到案发书房",
      toSceneId: "study",
      position: [-4.1, -0.9, 0.18],
      travelX: -3.6,
      direction: "side",
    },
  ],
};

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
      travelX: (characterHints[characterId] || fallbackCharacter(scene.characters.length, index))[0] - 0.35,
      travelY: -1.08,
    };
  });

  return { hotspots, characters, portals: scenePortals[scene.id] || [] };
}

function fallbackHotspot(
  total: number,
  index: number,
  id: string,
): Omit<HotspotPlacement, "id"> {
  const angle = (Math.PI * 2 * index) / Math.max(1, total) - Math.PI / 2;
  const radius = 2.6 + (hash(id) % 5) * 0.12;
  const tone: HotspotPlacement["tone"][] = ["brass", "paper", "stone", "wine", "medicine"];
  const x = Math.cos(angle) * radius;
  return {
    position: [x, -0.74 + Math.sin(angle) * 0.62, 0.1],
    size: [0.72, 0.32, 0.08],
    tone: tone[hash(id) % tone.length],
    travelX: x,
    travelY: -1.08,
  };
}

function fallbackCharacter(total: number, index: number): Vec3 {
  const step = 3.2 / Math.max(1, total - 1 || 1);
  return [-1.6 + step * index, -1.0, 0.2];
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
