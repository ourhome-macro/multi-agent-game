import { Gavel, MessageCircle, Send, Search, ShieldAlert } from "lucide-react";
import { useMemo, useState } from "react";

import { useUiStore } from "../state/uiStore";
import type {
  PlayerAction,
  PublicCaseDetail,
  PublicScene,
  PublicStateSummary,
  SessionAffordances,
} from "../types/public-api";

type ActionMenuProps = {
  caseDetail: PublicCaseDetail;
  scene: PublicScene;
  state: PublicStateSummary | null;
  affordances: SessionAffordances | null;
  busy: boolean;
  onAction: (action: PlayerAction) => void;
};

export function ActionMenu({
  caseDetail,
  scene,
  state,
  affordances,
  busy,
  onAction,
}: ActionMenuProps) {
  const selection = useUiStore((store) => store.selection);
  const clearSelection = useUiStore((store) => store.clearSelection);
  const [talkText, setTalkText] = useState("");

  const selectedHotspot = useMemo(
    () =>
      selection.kind === "hotspot"
        ? scene.hotspots.find((hotspot) => hotspot.id === selection.id)
        : undefined,
    [scene.hotspots, selection],
  );
  const selectedCharacter = useMemo(
    () =>
      selection.kind === "character"
        ? caseDetail.characters.find((character) => character.id === selection.id)
        : undefined,
    [caseDetail.characters, selection],
  );

  if (selection.kind === "none") return null;

  if (selectedHotspot) {
    return (
      <section className="action-menu">
        <div>
          <strong>{selectedHotspot.name}</strong>
          <p>{selectedHotspot.description}</p>
        </div>
        <button
          className="primary-command"
          type="button"
          disabled={busy}
          onClick={() => onAction({ type: "inspect", target_id: selectedHotspot.id })}
        >
          <Search size={17} />
          检查
        </button>
        <button className="ghost-command" type="button" onClick={clearSelection}>
          关闭
        </button>
      </section>
    );
  }

  if (!selectedCharacter) return null;

  const askItems = affordances?.ask_about.filter((item) => item.target_id === selectedCharacter.id) || [];
  const presentItems =
    affordances?.present_clue.filter((item) => item.target_id === selectedCharacter.id) || [];
  const accuseItem = affordances?.accuse.find((item) => item.target_id === selectedCharacter.id);
  const discoveredTitles = new Set(state?.evidence_assets.map((item) => item.clue_id || item.id) || []);

  return (
    <section className="action-menu character-menu">
      <div className="character-summary">
        <strong>{selectedCharacter.display_name}</strong>
        <span>{selectedCharacter.public_role}</span>
        <p>{selectedCharacter.public_description}</p>
      </div>
      <div className="talk-row">
        <input
          value={talkText}
          onChange={(event) => setTalkText(event.target.value)}
          placeholder="输入一句话"
        />
        <button
          className="icon-command"
          type="button"
          title="对话"
          disabled={busy}
          onClick={() =>
            onAction({
              type: "talk",
              target_id: selectedCharacter.id,
              text: talkText.trim() || "你现在愿意说些什么？",
            })
          }
        >
          <MessageCircle size={17} />
        </button>
      </div>
      <div className="action-scroll">
        {askItems.map((item) => (
          <button
            key={`${item.target_id}-${item.subject_type}-${item.subject_id}`}
            className="secondary-command"
            type="button"
            disabled={busy}
            onClick={() =>
              onAction({
                type: "ask_about",
                target_id: item.target_id,
                subject_type: item.subject_type,
                subject_id: item.subject_id,
                text: `谈谈${item.subject_label}`,
              })
            }
          >
            <Send size={16} />
            问：{item.subject_label}
          </button>
        ))}
        {presentItems.map((item) => {
          const mode = item.presentation_modes.includes("private")
            ? "private"
            : item.presentation_modes[0];
          const sceneId = mode === "scene_shared" ? item.scene_ids[0] || scene.id : undefined;
          return (
            <button
              key={`${item.target_id}-${item.clue_id}`}
              className="secondary-command"
              type="button"
              disabled={busy || !discoveredTitles.has(item.clue_id)}
              onClick={() =>
                onAction({
                  type: "present_clue",
                  target_id: item.target_id,
                  clue_id: item.clue_id,
                  presentation_mode: mode,
                  scene_id: sceneId,
                  text: `请解释${item.clue_title}`,
                })
              }
            >
              <ShieldAlert size={16} />
              示证：{item.clue_title}
            </button>
          );
        })}
        {accuseItem ? (
          <button className="secondary-command is-disabled" type="button" disabled>
            <Gavel size={16} />
            正式指控待安全标识
          </button>
        ) : null}
      </div>
    </section>
  );
}
