export type ActionType =
  | "inspect"
  | "talk"
  | "ask_about"
  | "present_clue"
  | "accuse"
  | "meeting_start"
  | "meeting_speak"
  | "meeting_present_evidence"
  | "meeting_ask"
  | "meeting_open_vote"
  | "meeting_cast_vote"
  | "meeting_propose_verdict";
export type SubjectType = "clue" | "character" | "scene";
export type PresentationMode = "private" | "scene_shared";
export type MeetingVoteChoice = "accuse" | "defend" | "abstain";

export type CaseMeta = {
  id: string;
  title: string;
  description?: string;
  initial_phase: string;
};

export type PublicSceneHotspot = {
  id: string;
  name: string;
  description?: string;
};

export type PublicScene = {
  id: string;
  name: string;
  description?: string;
  characters: string[];
  hotspots: PublicSceneHotspot[];
};

export type PublicCharacter = {
  id: string;
  display_name: string;
  public_role: string;
  public_description?: string;
};

export type PublicCaseDetail = {
  id: string;
  title: string;
  description?: string;
  initial_phase: string;
  initial_scene_id: string;
  scenes: PublicScene[];
  characters: PublicCharacter[];
  assets: Array<{ id: string; type: string; url?: string | null; role?: string }>;
};

export type ClueSummary = {
  id: string;
  title: string;
  description?: string;
  source_hotspot_id?: string | null;
};

export type CharacterSummary = {
  id: string;
  display_name: string;
  public_role: string;
  public_description?: string;
};

export type PublicPlayerKnowledgeSummary = {
  clue_id?: string | null;
  confidence: number;
  acquisition: string;
  source_type: string;
  title: string;
  summary: string;
};

export type PublicEvidenceSummary = {
  id: string;
  title: string;
  summary: string;
  source: string;
  clue_id?: string | null;
};

export type RelationshipState = {
  source_id: string;
  target_id: string;
  trust?: number;
  suspicion?: number;
  fear?: number;
  intimacy?: number;
  hostility?: number;
};

export type NpcLocationSummary = {
  npc_id: string;
  scene_id: string;
};

export type MeetingVoteSummary = {
  voter_id: string;
  target_id: string;
  choice: MeetingVoteChoice;
  reason?: string | null;
};

export type MeetingStateSummary = {
  active: boolean;
  meeting_id?: string | null;
  topic?: string | null;
  participant_ids: string[];
  turn: number;
  vote_open: boolean;
  vote_target_id?: string | null;
  votes: MeetingVoteSummary[];
  verdict_target_id?: string | null;
  verdict_status?: string | null;
  verdict_result?: string | null;
  verdict_reason?: string | null;
  missing_required_evidence: string[];
  missing_required_world_info: string[];
};

export type PublicStateSummary = {
  session_id: string;
  case_id: string;
  case_title: string;
  narrative_phase: string;
  completed_beats: string[];
  characters: CharacterSummary[];
  discovered_clues: ClueSummary[];
  player_knowledge: PublicPlayerKnowledgeSummary[];
  evidence_assets: PublicEvidenceSummary[];
  npc_locations: NpcLocationSummary[];
  meeting: MeetingStateSummary;
  relationships: RelationshipState[];
  event_count: number;
};

export type PublicCreateSessionResponse = {
  session_id: string;
  state: PublicStateSummary;
};

export type InspectAffordance = {
  type: "inspect";
  target_id: string;
  scene_id: string;
  label: string;
  description?: string;
};

export type TalkAffordance = {
  type: "talk";
  target_id: string;
  scene_ids: string[];
  label: string;
  public_role: string;
};

export type AskAboutAffordance = {
  type: "ask_about";
  target_id: string;
  subject_type: SubjectType;
  subject_id: string;
  subject_label: string;
};

export type PresentClueAffordance = {
  type: "present_clue";
  target_id: string;
  clue_id: string;
  clue_title: string;
  presentation_modes: PresentationMode[];
  scene_ids: string[];
};

export type AccuseAffordance = {
  type: "accuse";
  target_id: string;
  evidence_clue_ids: string[];
};

export type SessionAffordances = {
  session_id: string;
  case_id: string;
  narrative_phase: string;
  event_count: number;
  available_hotspot_ids: string[];
  available_character_ids: string[];
  discovered_clue_ids: string[];
  evidence_asset_ids: string[];
  valid_presentation_modes: PresentationMode[];
  can_accuse: boolean;
  inspect: InspectAffordance[];
  talk: TalkAffordance[];
  ask_about: AskAboutAffordance[];
  present_clue: PresentClueAffordance[];
  accuse: AccuseAffordance[];
};

export type PublicEventStreamItem = {
  sequence: number;
  id: string;
  type: string;
  actor_id: string;
  created_at: string;
  payload: Record<string, unknown>;
};

export type PublicEventStreamResponse = {
  session_id: string;
  case_id: string;
  after_count: number;
  next_after_count: number;
  has_more: boolean;
  events: PublicEventStreamItem[];
};

export type PlayerAction = {
  type: ActionType;
  target_id: string;
  clue_id?: string;
  scene_id?: string;
  presentation_mode?: PresentationMode;
  claim_id?: string;
  evidence_clue_ids?: string[];
  subject_type?: SubjectType;
  subject_id?: string;
  vote?: MeetingVoteChoice;
  text?: string;
};

export type PublicActionResponse = {
  session_id: string;
  accepted: boolean;
  speech?: string | null;
  director_blocked: boolean;
  director_reason?: string | null;
  llm_fallback_used: boolean;
  llm_error?: unknown;
  new_events: PublicEventStreamItem[];
  state: PublicStateSummary;
};

export type PublicRawTextActionResponse = {
  status: string;
  action?: PlayerAction | null;
  response?: PublicActionResponse | null;
  reason?: string | null;
  missing_slots: string[];
  route_trace: Record<string, object>;
};

export type ApiErrorPayload = {
  code?: string;
  message?: string;
  detail?: unknown;
  details?: Record<string, unknown>;
  retryable?: boolean;
  correlation_id?: string;
};
