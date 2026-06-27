import { apiRequest, makeIdempotencyKey } from "./client";
import type {
  PlayerAction,
  PublicActionResponse,
  PublicCreateSessionResponse,
  PublicEventStreamResponse,
  PublicRawTextActionResponse,
  PublicStateSummary,
  SessionAffordances,
} from "../types/public-api";

export function createSession(caseId: string): Promise<PublicCreateSessionResponse> {
  return apiRequest<PublicCreateSessionResponse>("/sessions", {
    method: "POST",
    body: JSON.stringify({ case_id: caseId }),
  });
}

export function getSessionState(sessionId: string): Promise<PublicStateSummary> {
  return apiRequest<PublicStateSummary>(`/sessions/${encodeURIComponent(sessionId)}/state`);
}

export function getSessionAffordances(sessionId: string): Promise<SessionAffordances> {
  return apiRequest<SessionAffordances>(
    `/sessions/${encodeURIComponent(sessionId)}/affordances`,
  );
}

export function getSessionEvents(
  sessionId: string,
  afterCount = 0,
): Promise<PublicEventStreamResponse> {
  return apiRequest<PublicEventStreamResponse>(
    `/sessions/${encodeURIComponent(sessionId)}/events?after_count=${afterCount}&limit=300`,
  );
}

export function submitAction(
  sessionId: string,
  action: PlayerAction,
): Promise<PublicActionResponse> {
  return apiRequest<PublicActionResponse>(`/sessions/${encodeURIComponent(sessionId)}/actions`, {
    method: "POST",
    idempotencyKey: makeIdempotencyKey(action.type),
    body: JSON.stringify(action),
  });
}

export function submitRawAction(
  sessionId: string,
  rawText: string,
): Promise<PublicRawTextActionResponse> {
  return apiRequest<PublicRawTextActionResponse>(
    `/sessions/${encodeURIComponent(sessionId)}/raw-actions`,
    {
      method: "POST",
      idempotencyKey: makeIdempotencyKey("raw"),
      body: JSON.stringify({ raw_text: rawText }),
    },
  );
}
