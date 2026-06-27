import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getCaseDetail } from "./api/cases";
import {
  createSession,
  getSessionAffordances,
  getSessionEvents,
  getSessionState,
  submitAction,
  submitRawAction,
} from "./api/sessions";
import { ApiClientError } from "./api/client";
import { useSound } from "./audio/useSound";
import { GameCanvas } from "./game/GameCanvas";
import { useUiStore } from "./state/uiStore";
import { ActionMenu } from "./ui/ActionMenu";
import { DialoguePanel } from "./ui/DialoguePanel";
import { IntroOverlay } from "./ui/IntroOverlay";
import { MeetingPanel } from "./ui/MeetingPanel";
import { RawInput } from "./ui/RawInput";
import { SidePanel } from "./ui/SidePanel";
import { TopBar } from "./ui/TopBar";
import type { PlayerAction, PublicActionResponse } from "./types/public-api";

const FIRST_CASE_ID = "mist_clock_manor";

export function App() {
  const queryClient = useQueryClient();
  const sound = useSound();
  const bgmRef = useRef<HTMLAudioElement | null>(null);
  const [bgmUrl, setBgmUrl] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [dialogue, setDialogue] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [introVisible, setIntroVisible] = useState(true);
  const [journalOpen, setJournalOpen] = useState(false);
  const [meetingOpen, setMeetingOpen] = useState(false);
  const currentSceneId = useUiStore((store) => store.currentSceneId);
  const setCurrentSceneId = useUiStore((store) => store.setCurrentSceneId);
  const clearSelection = useUiStore((store) => store.clearSelection);
  const setActivePanel = useUiStore((store) => store.setActivePanel);

  const caseQuery = useQuery({
    queryKey: ["case", FIRST_CASE_ID],
    queryFn: () => getCaseDetail(FIRST_CASE_ID),
  });

  const createSessionMutation = useMutation({
    mutationFn: () => createSession(FIRST_CASE_ID),
    onSuccess: (response) => {
      setSessionId(response.session_id);
      queryClient.setQueryData(["state", response.session_id], response.state);
      setDialogue("雨停之前，书房里的每一道痕迹都不会自己开口。");
      setWarning(null);
    },
    onError: (error) => {
      setWarning(formatError(error));
      void sound.play("error");
    },
  });

  useEffect(() => {
    if (!caseQuery.data || sessionId || createSessionMutation.isPending) return;
    createSessionMutation.mutate();
  }, [caseQuery.data, createSessionMutation, sessionId]);

  useEffect(() => {
    if (caseQuery.data && !currentSceneId) {
      setCurrentSceneId(caseQuery.data.initial_scene_id);
    }
  }, [caseQuery.data, currentSceneId, setCurrentSceneId]);

  const stateQuery = useQuery({
    queryKey: ["state", sessionId],
    queryFn: () => getSessionState(sessionId as string),
    enabled: Boolean(sessionId),
  });

  const affordancesQuery = useQuery({
    queryKey: ["affordances", sessionId],
    queryFn: () => getSessionAffordances(sessionId as string),
    enabled: Boolean(sessionId),
    refetchInterval: 12_000,
  });

  const eventsQuery = useQuery({
    queryKey: ["events", sessionId],
    queryFn: () => getSessionEvents(sessionId as string, 0),
    enabled: Boolean(sessionId),
    refetchInterval: meetingOpen ? 3_000 : false,
  });

  const applyActionResponse = useCallback(
    (response: PublicActionResponse) => {
      queryClient.setQueryData(["state", response.session_id], response.state);
      setWarning(null);
      if (response.director_blocked) {
        setWarning(response.director_reason || "这句话被雾声吞没了。");
      }
      if (!response.accepted) {
        const rejection = response.new_events.find((event) => event.type === "rule.rejected");
        const reason = rejection?.payload.reason;
        setWarning(typeof reason === "string" ? reason : "现在还不能这么做。");
      }
      if (response.speech) {
        setDialogue(response.speech);
      } else if (response.new_events.length > 0) {
        setDialogue(publicEventSummary(response.new_events));
      }

      const eventTypes = new Set(response.new_events.map((event) => event.type));
      if (response.director_blocked || !response.accepted) {
        void sound.play("error");
      } else if (eventTypes.has("narrative.phase.changed")) {
        void sound.play("phase");
      } else if (eventTypes.has("clue.discovered") || eventTypes.has("player_knowledge.updated")) {
        void sound.play("clue");
      } else if (eventTypes.has("npc.replied")) {
        void sound.play("dialogue");
      } else {
        void sound.play("click");
      }

      void queryClient.invalidateQueries({ queryKey: ["affordances", response.session_id] });
      void queryClient.invalidateQueries({ queryKey: ["events", response.session_id] });
    },
    [queryClient, sound],
  );

  const actionMutation = useMutation({
    mutationFn: (action: PlayerAction) => {
      if (!sessionId) throw new Error("Session is not ready");
      return submitAction(sessionId, action);
    },
    onSuccess: applyActionResponse,
    onError: (error) => {
      setWarning(formatError(error));
      void sound.play("error");
    },
  });

  const rawMutation = useMutation({
    mutationFn: (text: string) => {
      if (!sessionId) throw new Error("Session is not ready");
      return submitRawAction(sessionId, text);
    },
    onSuccess: (response) => {
      if (response.response) {
        applyActionResponse(response.response);
        return;
      }
      setWarning(response.reason || "输入需要进一步澄清。");
      setDialogue(null);
      void sound.play("error");
    },
    onError: (error) => {
      setWarning(formatError(error));
      void sound.play("error");
    },
  });

  const busy =
    createSessionMutation.isPending || actionMutation.isPending || rawMutation.isPending;

  const caseDetail = caseQuery.data;
  const activeSceneId = currentSceneId || caseDetail?.initial_scene_id || "study";
  const scene = useMemo(
    () =>
      caseDetail?.scenes.find((item) => item.id === activeSceneId) ||
      caseDetail?.scenes[0] ||
      null,
    [caseDetail, activeSceneId],
  );
  const state = stateQuery.data || null;
  const affordances = affordancesQuery.data || null;

  const resetSession = useCallback(() => {
    if (sessionId) {
      queryClient.removeQueries({ queryKey: ["state", sessionId] });
      queryClient.removeQueries({ queryKey: ["affordances", sessionId] });
    }
    setSessionId(null);
    setDialogue("雨停之前，书房里的每一道痕迹都不会自己开口。");
    setWarning(null);
    clearSelection();
    createSessionMutation.mutate();
  }, [clearSelection, createSessionMutation, queryClient, sessionId]);

  const handleBgmFile = useCallback((file: File | null) => {
    if (bgmUrl) URL.revokeObjectURL(bgmUrl);
    if (!file) {
      setBgmUrl(null);
      return;
    }
    const nextUrl = URL.createObjectURL(file);
    setBgmUrl(nextUrl);
    window.setTimeout(() => {
      void bgmRef.current?.play();
    }, 0);
  }, [bgmUrl]);

  useEffect(() => () => {
    if (bgmUrl) URL.revokeObjectURL(bgmUrl);
  }, [bgmUrl]);

  if (caseQuery.isLoading || !caseDetail || !scene) {
    return <BootScreen message="雾正在漫过山路..." />;
  }

  if (caseQuery.isError) {
    return <BootScreen message={formatError(caseQuery.error)} />;
  }

  return (
    <main className="app-shell">
      <TopBar
        sfxEnabled={sound.enabled}
        sfxVolume={sound.volume}
        onToggleSfx={sound.setEnabled}
        onSfxVolume={sound.setVolume}
        onBgmFile={handleBgmFile}
        onReset={resetSession}
        onOpenJournal={() => {
          setActivePanel("story");
          setJournalOpen(true);
        }}
        onOpenMeeting={() => setMeetingOpen(true)}
      />
      <GameCanvas
        caseDetail={caseDetail}
        state={state}
        affordances={affordances}
        currentSceneId={scene.id}
        busy={busy}
        onAction={(action) => actionMutation.mutate(action)}
        onSound={(name) => void sound.play(name)}
      />
      <SidePanel
        caseDetail={caseDetail}
        scene={scene}
        state={state}
        open={journalOpen}
        onClose={() => setJournalOpen(false)}
      />
      <ActionMenu
        caseDetail={caseDetail}
        scene={scene}
        state={state}
        affordances={affordances}
        busy={busy || !sessionId}
        onAction={(action) => actionMutation.mutate(action)}
      />
      <DialoguePanel title={warning ? "雾中回声" : "旁白"} message={dialogue} warning={warning} />
      <MeetingPanel
        caseDetail={caseDetail}
        state={state}
        affordances={affordances}
        events={eventsQuery.data?.events || []}
        open={meetingOpen}
        busy={busy || !sessionId}
        onAction={(action) => actionMutation.mutate(action)}
        onClose={() => setMeetingOpen(false)}
        onAppendNarration={setDialogue}
      />
      <RawInput disabled={busy || !sessionId} onSubmit={(text) => rawMutation.mutate(text)} />
      <IntroOverlay
        visible={introVisible}
        onContinue={() => {
          setIntroVisible(false);
          void sound.play("phase");
        }}
      />
      {bgmUrl ? <audio ref={bgmRef} src={bgmUrl} loop controls className="bgm-player" /> : null}
    </main>
  );
}

function BootScreen({ message }: { message: string }) {
  return (
    <main className="boot-screen">
      <div>
        <strong>agent剧本杀</strong>
        <span>{message}</span>
      </div>
    </main>
  );
}

function publicEventSummary(events: PublicActionResponse["new_events"]): string {
  const clue = events.find((event) => event.type === "clue.discovered");
  if (clue && typeof clue.payload.clue_id === "string") {
    return "你发现了一条新的线索。";
  }
  const phase = events.find((event) => event.type === "narrative.phase.changed");
  if (phase) {
    return "山庄里的空气变了。";
  }
  const event = events[events.length - 1];
  return event ? "这一刻被记录了下来。" : "你停下脚步。";
}

function formatError(error: unknown): string {
  if (error instanceof ApiClientError) {
    const detail = error.payload.details?.reason || error.payload.detail;
    if (typeof detail === "string") return detail;
    return error.payload.message || error.payload.code || `HTTP ${error.status}`;
  }
  if (error instanceof Error) return error.message;
  return "未知错误";
}
