import { useMemo } from "react";

import { HotspotMesh } from "./HotspotMesh";
import { NpcActor } from "./NpcActor";
import { RoomScene } from "./RoomScene";
import { buildScenePresentation } from "./layout";
import { useUiStore } from "../state/uiStore";
import type {
  PlayerAction,
  PublicCaseDetail,
  PublicStateSummary,
  SessionAffordances,
} from "../types/public-api";

type SceneRendererProps = {
  caseDetail: PublicCaseDetail;
  state: PublicStateSummary | null;
  affordances: SessionAffordances | null;
  currentSceneId: string;
  busy: boolean;
  onAction: (action: PlayerAction) => void;
  onSound: (name: "hover" | "click" | "inspect" | "clue" | "dialogue" | "phase" | "error") => void;
};

export function SceneRenderer({
  caseDetail,
  state,
  affordances,
  currentSceneId,
  busy,
  onAction,
  onSound,
}: SceneRendererProps) {
  const scene = caseDetail.scenes.find((item) => item.id === currentSceneId) || caseDetail.scenes[0];
  const selection = useUiStore((store) => store.selection);
  const selectHotspot = useUiStore((store) => store.selectHotspot);
  const selectCharacter = useUiStore((store) => store.selectCharacter);
  const setHoveredId = useUiStore((store) => store.setHoveredId);
  const presentation = useMemo(
    () => buildScenePresentation(scene, caseDetail),
    [scene, caseDetail],
  );

  const discoveredIds = new Set(state?.discovered_clues.map((clue) => clue.id) || []);
  const inspectableIds = new Set(affordances?.available_hotspot_ids || []);
  const talkableIds = new Set(affordances?.available_character_ids || []);

  return (
    <group>
      <RoomScene sceneId={scene.id} />
      {scene.hotspots.map((hotspot) => {
        const placement = presentation.hotspots.find((item) => item.id === hotspot.id);
        if (!placement) return null;
        const enabled = inspectableIds.has(hotspot.id) && !busy;
        return (
          <HotspotMesh
            key={hotspot.id}
            hotspot={hotspot}
            placement={placement}
            enabled={enabled}
            discovered={discoveredIds.has(hotspot.id)}
            selected={selection.kind === "hotspot" && selection.id === hotspot.id}
            onHover={(id) => {
              setHoveredId(id);
              if (id) onSound("hover");
            }}
            onSelect={() => {
              selectHotspot(hotspot.id);
              onSound("inspect");
              if (enabled) onAction({ type: "inspect", target_id: hotspot.id });
            }}
          />
        );
      })}
      {scene.characters.map((characterId) => {
        const placement = presentation.characters.find((item) => item.id === characterId);
        const character = caseDetail.characters.find((item) => item.id === characterId);
        if (!placement || !character) return null;
        const enabled = talkableIds.has(characterId) && !busy;
        return (
          <NpcActor
            key={characterId}
            character={character}
            placement={placement}
            enabled={enabled}
            selected={selection.kind === "character" && selection.id === characterId}
            onHover={(id) => {
              setHoveredId(id);
              if (id) onSound("hover");
            }}
            onSelect={() => {
              selectCharacter(characterId);
              onSound("click");
            }}
          />
        );
      })}
    </group>
  );
}
