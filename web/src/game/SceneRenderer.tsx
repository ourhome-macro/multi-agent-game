import { useMemo } from "react";

import { HotspotMesh } from "./HotspotMesh";
import { CameraRig } from "./CameraRig";
import { KeyboardController } from "./KeyboardController";
import { NpcActor } from "./NpcActor";
import { PlayerActor } from "./PlayerActor";
import { PortalMarker } from "./PortalMarker";
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
  const hoveredId = useUiStore((store) => store.hoveredId);
  const playerX = useUiStore((store) => store.playerX);
  const playerY = useUiStore((store) => store.playerY);
  const setCurrentSceneId = useUiStore((store) => store.setCurrentSceneId);
  const selectHotspot = useUiStore((store) => store.selectHotspot);
  const selectCharacter = useUiStore((store) => store.selectCharacter);
  const setHoveredId = useUiStore((store) => store.setHoveredId);
  const setPlayerTarget = useUiStore((store) => store.setPlayerTarget);
  const setPlayerMotion = useUiStore((store) => store.setPlayerMotion);
  const presentation = useMemo(
    () => buildScenePresentation(scene, caseDetail),
    [scene, caseDetail],
  );

  const discoveredIds = new Set(state?.discovered_clues.map((clue) => clue.id) || []);
  const inspectableIds = new Set(affordances?.available_hotspot_ids || []);
  const talkableIds = new Set(affordances?.available_character_ids || []);
  const activeTalkingCharacter = selection.kind === "character" ? selection.id : null;

  return (
    <group>
      <KeyboardController />
      <CameraRig playerX={playerX} playerY={playerY} />
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
            hovered={hoveredId === hotspot.id}
            onHover={(id) => {
              setHoveredId(id);
              if (id) onSound("hover");
            }}
            onSelect={() => {
              selectHotspot(hotspot.id);
              setPlayerTarget(placement.travelX, placement.travelY ?? -1.08);
              setPlayerMotion("walk");
              onSound("inspect");
              if (enabled) {
                window.setTimeout(() => {
                  setPlayerMotion("interact");
                  onAction({ type: "inspect", target_id: hotspot.id });
                }, 520);
              }
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
            mode={activeTalkingCharacter === characterId ? "talk" : "idle"}
            onHover={(id) => {
              setHoveredId(id);
              if (id) onSound("hover");
            }}
            onSelect={() => {
              selectCharacter(characterId);
              setPlayerTarget(placement.travelX, placement.travelY ?? -1.08);
              setPlayerMotion("walk");
              window.setTimeout(() => setPlayerMotion("talk"), 520);
              onSound("click");
            }}
          />
        );
      })}
      {presentation.portals.map((portal) => (
        <PortalMarker
          key={portal.id}
          portal={portal}
          busy={busy}
          selected={selection.kind === "none" && false}
          onHover={(id) => {
            setHoveredId(id);
            if (id) onSound("hover");
          }}
          onSelect={() => {
            setPlayerTarget(portal.travelX, portal.travelY ?? -1.08);
            setPlayerMotion("walk");
            onSound("phase");
            window.setTimeout(() => setCurrentSceneId(portal.toSceneId), 620);
          }}
        />
      ))}
      <PlayerActor />
    </group>
  );
}
