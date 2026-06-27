import { FileText, Gavel, MessageCircleQuestion, Send, Vote, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { getCharacterArt } from "../assets/artAssets";
import type {
  MeetingVoteChoice,
  PlayerAction,
  PublicCaseDetail,
  PublicCharacter,
  PublicEventStreamItem,
  PublicEvidenceSummary,
  PublicStateSummary,
  SessionAffordances,
} from "../types/public-api";

type MeetingPanelProps = {
  open: boolean;
  caseDetail: PublicCaseDetail;
  state: PublicStateSummary | null;
  affordances: SessionAffordances | null;
  events: PublicEventStreamItem[];
  busy: boolean;
  onClose: () => void;
  onAction: (action: PlayerAction) => void;
  onAppendNarration: (text: string) => void;
};

type MeetingMessage = {
  id: string;
  speaker: string;
  text: string;
  mine?: boolean;
  system?: boolean;
  danger?: boolean;
};

const ui = {
  title: "山庄会议",
  subtitle: "公开讨论 / 点名回应 / 投票 / 最终裁决",
  close: "关闭会议",
  roster: "参会者",
  record: "会议记录",
  player: "沈照夜",
  evidence: "公开证据",
  verdict: "最终裁决",
  startTitle: "召集会议",
  startTopic: "案件公开讨论",
  startButton: "开始",
  placeholder: "把当前推理发到会议里",
  send: "发言",
  ask: "提问",
  present: "展示",
  noEvidence: "还没有可公开核对的证据。",
  noVerdict: "还没到可裁决阶段。",
  role: "会议成员",
  vote: "投票",
  openVote: "开票",
  proposeVerdict: "提交裁决",
  selectAll: "全选",
  clear: "清空",
  rejection: "裁决被规则拒绝",
};

const voteChoices: MeetingVoteChoice[] = ["accuse", "defend", "abstain"];
const voteLabels: Record<MeetingVoteChoice, string> = {
  accuse: "指认",
  defend: "辩护",
  abstain: "弃权",
};

const emptyMessages: MeetingMessage[] = [
  {
    id: "meeting-empty-1",
    speaker: ui.record,
    text: "所有公开发言、证据展示和投票都会进入事件日志。",
    system: true,
  },
  {
    id: "meeting-empty-2",
    speaker: ui.record,
    text: "投票只能表达立场，最终裁决必须经过规则引擎校验证据链。",
    system: true,
  },
];

export function MeetingPanel({
  open,
  caseDetail,
  state,
  affordances,
  events,
  busy,
  onClose,
  onAction,
  onAppendNarration,
}: MeetingPanelProps) {
  const [draft, setDraft] = useState("");
  const [topic, setTopic] = useState(ui.startTopic);
  const [selectedId, setSelectedId] = useState(caseDetail.characters[0]?.id || "");
  const [selectedEvidenceIds, setSelectedEvidenceIds] = useState<string[]>([]);

  const meeting = state?.meeting;
  const activeMeeting = true;
  const evidence = state?.evidence_assets || [];
  const charactersById = useMemo(
    () => new Map(caseDetail.characters.map((character) => [character.id, character])),
    [caseDetail.characters],
  );
  const roster = useMemo<PublicCharacter[]>(() => {
    const participantIds = meeting?.participant_ids || [];
    if (participantIds.length === 0) return caseDetail.characters;
    return participantIds
      .map((id) => charactersById.get(id))
      .filter((character): character is PublicCharacter => Boolean(character));
  }, [caseDetail.characters, charactersById, meeting?.participant_ids]);
  const selected = charactersById.get(selectedId) || roster[0];
  const selectedName = selected?.display_name || selectedId;
  const selectedEvidenceSet = useMemo(
    () => new Set(selectedEvidenceIds),
    [selectedEvidenceIds],
  );
  const messages = useMemo(
    () => buildMeetingMessages(events, charactersById),
    [charactersById, events],
  );
  const requiredEvidence =
    affordances?.accuse.find((item) => item.target_id === selectedId)?.evidence_clue_ids || [];
  const missingEvidence = meeting?.missing_required_evidence || [];
  const missingWorldInfo = meeting?.missing_required_world_info || [];

  useEffect(() => {
    if (roster.length > 0 && !roster.some((character) => character.id === selectedId)) {
      setSelectedId(roster[0].id);
    }
  }, [roster, selectedId]);

  if (!open) return null;

  const startMeeting = () => {
    onAction({
      type: "meeting_start",
      target_id: "meeting",
      text: topic.trim() || ui.startTopic,
    });
    onAppendNarration("山庄会议已经被召集。");
  };

  const speak = () => {
    const value = draft.trim();
    if (!value) return;
    onAction({ type: "meeting_speak", target_id: "meeting", text: value });
    setDraft("");
  };

  const ask = () => {
    if (!selectedId) return;
    const value = draft.trim() || `请${selectedName}回应当前议题。`;
    onAction({ type: "meeting_ask", target_id: selectedId, text: value });
    setDraft("");
  };

  const presentEvidence = (item: PublicEvidenceSummary) => {
    onAction({
      type: "meeting_present_evidence",
      target_id: "meeting",
      clue_id: evidenceClueId(item),
      text: `展示证据：${item.title}`,
    });
  };

  const openVote = () => {
    if (!selectedId) return;
    onAction({
      type: "meeting_open_vote",
      target_id: selectedId,
      text: `是否认为${selectedName}嫌疑最高？`,
    });
  };

  const castVote = (vote: MeetingVoteChoice) => {
    if (!meeting?.vote_target_id) return;
    onAction({
      type: "meeting_cast_vote",
      target_id: meeting.vote_target_id,
      vote,
      text: `玩家会议投票：${voteLabels[vote]}`,
    });
  };

  const proposeVerdict = () => {
    if (!selectedId) return;
    onAction({
      type: "meeting_propose_verdict",
      target_id: selectedId,
      evidence_clue_ids: selectedEvidenceIds,
      text: `会议裁决：指认${selectedName}`,
    });
  };

  return (
    <section className="meeting-panel" aria-label={ui.title}>
      <header className="meeting-header">
        <div>
          <strong>{ui.title}</strong>
          <span>{ui.subtitle}</span>
        </div>
        <button className="icon-button" type="button" title={ui.close} onClick={onClose}>
          <X size={18} />
        </button>
      </header>

      <div className="meeting-body">
        <aside className="meeting-roster" aria-label={ui.roster}>
          {roster.map((character) => (
            <button
              className={selectedId === character.id ? "is-selected" : undefined}
              key={character.id}
              type="button"
              onClick={() => setSelectedId(character.id)}
            >
              <span>{character.display_name}</span>
              <small>{character.public_role || ui.role}</small>
            </button>
          ))}
        </aside>

        <div className="meeting-chat">
          {!activeMeeting ? (
            <div className="meeting-start">
              <strong>{ui.startTitle}</strong>
              <input
                value={topic}
                disabled={busy}
                onChange={(event) => setTopic(event.target.value)}
              />
              <button
                className="primary-action"
                type="button"
                disabled={busy}
                onClick={startMeeting}
              >
                {ui.startButton}
              </button>
            </div>
          ) : (
            <>
              <div className="meeting-timeline">
                {(messages.length > 0 ? messages : emptyMessages).map((message) =>
                  message.system ? (
                    <div
                      className={
                        message.danger
                          ? "meeting-system-line is-danger"
                          : "meeting-system-line"
                      }
                      key={message.id}
                    >
                      {message.text}
                    </div>
                  ) : (
                    <article
                      className={message.mine ? "meeting-message is-player" : "meeting-message"}
                      key={message.id}
                    >
                      <strong>{message.speaker}</strong>
                      <p>{message.text}</p>
                    </article>
                  ),
                )}
              </div>

              <div className="meeting-composer">
                <input
                  value={draft}
                  disabled={busy}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") speak();
                  }}
                  placeholder={ui.placeholder}
                />
                <button
                  className="icon-command"
                  type="button"
                  title={ui.send}
                  disabled={busy || !draft.trim()}
                  onClick={speak}
                >
                  <Send size={17} />
                </button>
                <button
                  className="icon-command"
                  type="button"
                  title={ui.ask}
                  disabled={busy || !selectedId}
                  onClick={ask}
                >
                  <MessageCircleQuestion size={17} />
                </button>
              </div>
            </>
          )}
        </div>

        <aside className="meeting-tools">
          <section>
            <div className="meeting-tools-heading">
              <strong>{ui.evidence}</strong>
              <button
                type="button"
                disabled={busy || evidence.length === 0}
                onClick={() =>
                  setSelectedEvidenceIds(
                    selectedEvidenceIds.length === evidence.length
                      ? []
                      : evidence.map(evidenceClueId),
                  )
                }
              >
                {selectedEvidenceIds.length === evidence.length ? ui.clear : ui.selectAll}
              </button>
            </div>
            {evidence.length === 0 ? <p className="meeting-empty">{ui.noEvidence}</p> : null}
            <div className="meeting-evidence-picker">
              {evidence.map((item) => {
                const clueId = evidenceClueId(item);
                return (
                  <label className="meeting-evidence-choice" key={item.id}>
                    <input
                      type="checkbox"
                      checked={selectedEvidenceSet.has(clueId)}
                      onChange={(event) =>
                        setSelectedEvidenceIds((current) =>
                          event.target.checked
                            ? [...new Set([...current, clueId])]
                            : current.filter((id) => id !== clueId),
                        )
                      }
                    />
                    <span>
                      <strong>{item.title}</strong>
                      <small>{item.summary}</small>
                    </span>
                    <button
                      className="meeting-inline-action"
                      type="button"
                      disabled={busy || !activeMeeting}
                      onClick={(event) => {
                        event.preventDefault();
                        presentEvidence(item);
                      }}
                    >
                      <FileText size={14} />
                      {ui.present}
                    </button>
                  </label>
                );
              })}
            </div>
          </section>

          <section>
            <div className="meeting-tools-heading">
              <strong>{ui.vote}</strong>
              <button type="button" disabled={busy || !activeMeeting} onClick={openVote}>
                <Vote size={14} />
                {ui.openVote}
              </button>
            </div>
            {meeting?.vote_open && meeting.vote_target_id ? (
              <>
                <p className="meeting-empty">
                  {ui.vote}: {displayCharacter(meeting.vote_target_id, charactersById)}
                </p>
                <div className="meeting-vote-buttons">
                  {voteChoices.map((vote) => (
                    <button key={vote} type="button" disabled={busy} onClick={() => castVote(vote)}>
                      <Vote size={16} />
                      <span>{voteLabels[vote]}</span>
                    </button>
                  ))}
                </div>
              </>
            ) : null}
          </section>

          <section>
            <h3>{ui.verdict}</h3>
            <div className="meeting-vote-buttons">
              {roster.map((character) => {
                const art = getCharacterArt(character);
                return (
                  <button
                    key={character.id}
                    type="button"
                    disabled={busy}
                    title={character.display_name}
                    onClick={() => setSelectedId(character.id)}
                  >
                    {art ? <img src={art.src} alt="" /> : <Gavel size={16} />}
                    <span>{character.display_name}</span>
                  </button>
                );
              })}
            </div>
            {requiredEvidence.length > 0 ? (
              <p className="meeting-empty">
                {selectedName}: {requiredEvidence.length} 条核心证据条件
              </p>
            ) : (
              <p className="meeting-empty">{ui.noVerdict}</p>
            )}
            <button
              className="primary-action"
              type="button"
              disabled={busy || !activeMeeting || selectedEvidenceIds.length === 0}
              onClick={proposeVerdict}
            >
              {ui.proposeVerdict}
            </button>
            {meeting?.verdict_status === "rejected" ? (
              <div className="meeting-verdict-rejection">
                <strong>{ui.rejection}</strong>
                {meeting.verdict_reason ? <p>{meeting.verdict_reason}</p> : null}
                {missingEvidence.length > 0 ? (
                  <ul>
                    {missingEvidence.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : null}
                {missingWorldInfo.length > 0 ? <span>{missingWorldInfo.join(" / ")}</span> : null}
              </div>
            ) : null}
          </section>
        </aside>
      </div>
    </section>
  );
}

function buildMeetingMessages(
  events: PublicEventStreamItem[],
  charactersById: Map<string, PublicCharacter>,
): MeetingMessage[] {
  return events
    .map((event): MeetingMessage | null => {
      const payload = event.payload;
      if (event.type === "meeting.message.posted") {
        const speakerId = stringField(payload, "speaker_id") || event.actor_id;
        const kind = stringField(payload, "message_kind");
        const body = stringField(payload, "text") || "";
        return {
          id: event.id,
          speaker: displayCharacter(speakerId, charactersById),
          text: `${kind === "evidence" ? "展示证据：" : ""}${body}`,
          mine: speakerId === "player",
          system: speakerId === "director",
        };
      }
      if (event.type === "meeting.vote.opened") {
        return systemMessage(
          event.id,
          `开始投票：${displayCharacter(stringField(payload, "target_id") || "", charactersById)}`,
        );
      }
      if (event.type === "meeting.vote.cast") {
        const voterId = stringField(payload, "voter_id") || event.actor_id;
        const targetId = stringField(payload, "target_id") || "";
        const choice = stringField(payload, "choice");
        const reason = stringField(payload, "reason");
        return systemMessage(
          event.id,
          `${displayCharacter(voterId, charactersById)} 对 ${displayCharacter(
            targetId,
            charactersById,
          )} 投票：${voteLabel(choice)}${reason ? `，${reason}` : ""}`,
        );
      }
      if (event.type === "meeting.verdict.proposed") {
        return systemMessage(
          event.id,
          `提交裁决：${displayCharacter(stringField(payload, "target_id") || "", charactersById)}`,
        );
      }
      if (event.type === "meeting.verdict.accepted") {
        return systemMessage(
          event.id,
          `裁决通过：${displayCharacter(stringField(payload, "target_id") || "", charactersById)}`,
        );
      }
      if (event.type === "meeting.verdict.rejected") {
        return systemMessage(event.id, stringField(payload, "reason") || "裁决未通过。", true);
      }
      return null;
    })
    .filter((message): message is MeetingMessage => Boolean(message))
    .slice(-40);
}

function systemMessage(id: string, body: string, danger = false): MeetingMessage {
  return { id, speaker: ui.record, text: body, system: true, danger };
}

function displayCharacter(id: string, charactersById: Map<string, PublicCharacter>): string {
  if (id === "player") return ui.player;
  if (id === "director") return ui.record;
  return charactersById.get(id)?.display_name || id;
}

function voteLabel(value: string | null): string {
  if (value === "accuse" || value === "defend" || value === "abstain") {
    return voteLabels[value];
  }
  return "未知";
}

function stringField(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key];
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  return normalized || null;
}

function evidenceClueId(item: PublicEvidenceSummary): string {
  return item.clue_id || item.id;
}
