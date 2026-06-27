export type SceneArt = {
  src: string;
  width: number;
  height: number;
};

export type CharacterArt = {
  src: string;
  width: number;
  height: number;
};

const assetVersion = "20260627d";
const asset = (path: string) => `${path}?v=${assetVersion}`;

export const sceneArtById: Record<string, SceneArt> = {
  study: { src: asset("/game-assets/scenes/study.png"), width: 1448, height: 510 },
  gallery: { src: asset("/game-assets/scenes/gallery.png"), width: 1448, height: 450 },
  clock_tower: { src: asset("/game-assets/scenes/tower.png"), width: 1448, height: 520 },
};

export const characterArtById: Record<string, CharacterArt> = {
  shen_zhaoye: { src: asset("/game-assets/characters/shen-zhaoye.png"), width: 210, height: 560 },
  lin_qichi: { src: asset("/game-assets/characters/lin-qichi.png"), width: 198, height: 620 },
  qi_yan: { src: asset("/game-assets/characters/qi-yan.png"), width: 208, height: 610 },
  jiang_yanhui: { src: asset("/game-assets/characters/jiang-yanhui.png"), width: 182, height: 625 },
};

export const playerArt = characterArtById.shen_zhaoye;

const characterAliases: Record<string, keyof typeof characterArtById> = {
  "\u6c88\u7167\u591c": "shen_zhaoye",
  "\u6797\u6816\u8fdf": "lin_qichi",
  "\u7941\u5bb4": "qi_yan",
  "\u6c5f\u96c1\u56de": "jiang_yanhui",
};

export function getCharacterArt(character?: { id: string; display_name?: string } | null): CharacterArt | null {
  if (!character) return null;
  return characterArtById[character.id] || characterArtById[characterAliases[character.display_name || ""]] || null;
}

const clueImageById: Record<string, string> = {
  bitter_wine: asset("/game-assets/clues/clue-01.png"),
  delayed_lock_marks: asset("/game-assets/clues/clue-02.png"),
  echo_tape: asset("/game-assets/clues/clue-03.png"),
  burned_confession: asset("/game-assets/clues/clue-04.png"),
  ruolan_voice_tape: asset("/game-assets/clues/clue-05.png"),
  empty_capsules: asset("/game-assets/clues/clue-06.png"),
  cut_power_trace: asset("/game-assets/clues/clue-07.png"),
  backup_timer: asset("/game-assets/clues/clue-08.png"),
  breaker_sequence_tag: asset("/game-assets/clues/clue-09.png"),
  fresh_gear_oil: asset("/game-assets/clues/clue-10.png"),
  muted_bell_hammer: asset("/game-assets/clues/clue-11.png"),
  lock_test_scrap: asset("/game-assets/clues/clue-12.png"),
  trust_indent_page: asset("/game-assets/clues/clue-13.png"),
  capsule_powder_on_liner: asset("/game-assets/clues/clue-14.png"),
  sedative_bottle_label: asset("/game-assets/clues/clue-15.png"),
  tape_splice_mark: asset("/game-assets/clues/clue-16.png"),
  pocket_watch_offset: asset("/game-assets/clues/clue-17.png"),
  covered_ruolan_photo: asset("/game-assets/clues/clue-18.png"),
  altered_gallery_plaque: asset("/game-assets/clues/clue-19.png"),
  lake_death_clipping: asset("/game-assets/clues/clue-20.png"),
  incomplete_evidence_box: asset("/game-assets/clues/clue-21.png"),
  gallery_mud_trace: asset("/game-assets/clues/clue-22.png"),
  missing_visitor_log_page: asset("/game-assets/clues/clue-23.png"),
};

export function getClueImage(clueId?: string | null): string | null {
  if (!clueId) return null;
  return clueImageById[clueId] || null;
}
