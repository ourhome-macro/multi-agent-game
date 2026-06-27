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
import { RawInput } from "./ui/RawInput";
import { SceneTabs } from "./ui/SceneTabs";
import { SidePanel } from "./ui/SidePanel";
import { TopBar } from "./ui/TopBar";
import type {
  PlayerAction,
  PublicActionResponse,
  PublicEventStreamItem,
} from "./types/public-api";

const FIRST_CASE_ID = "mist_clock_manor";

export function App() {
  const queryClient = useQueryClient();
  const sound = useSound();
  const bgmRef = useRef<HTMLAudioElement | null>(null);
  const [bgmUrl, setBgmUrl] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [dialogue, setDialogue] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const currentSceneId = useUiStore((store) => store.currentSceneId);
  const setCurrentSceneId = useUiStore((store) => store.setCurrentSceneId);
  const clearSelection = useUiStore((store) => store.clearSelection);

  const caseQuery = useQuery({
    queryKey: ["case", FIRST_CASE_ID],
    queryFn: () => getCaseDetail(FIRST_CASE_ID),
  });

  const createSessionMutation = useMutation({
    mutationFn: () => createSession(FIRST_CASE_ID),
    onSuccess: (response) => {
      setSessionId(response.session_id);
      queryClient.setQueryData(["state", response.session_id], response.state);
      setDialogue("新的调查会话已创建。");
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
  });

  const applyActionResponse = useCallback(
    (response: PublicActionResponse) => {
      queryClient.setQueryData(["state", response.session_id], response.state);
      setWarning(null);
      if (response.director_blocked) {
        setWarning(response.director_reason || "本轮回复被 Narrative Director 拦截。");
      }
      if (!response.accepted) {
        const rejection = response.new_events.find((event) => event.type === "rule.rejected");
        const reason = rejection?.payload.reason;
        setWarning(typeof reason === "string" ? reason : "行动未被当前规则接受。");
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
  const events = eventsQuery.data?.events || [];
  const connected = Boolean(caseDetail && sessionId && !caseQuery.isError);

  const resetSession = useCallback(() => {
    if (sessionId) {
      queryClient.removeQueries({ queryKey: ["state", sessionId] });
      queryClient.removeQueries({ queryKey: ["affordances", sessionId] });
      queryClient.removeQueries({ queryKey: ["events", sessionId] });
    }
    setSessionId(null);
    setDialogue(null);
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
    return <BootScreen message="正在连接雾钟山庄运行时..." />;
  }

  if (caseQuery.isError) {
    return <BootScreen message={formatError(caseQuery.error)} />;
  }

  return (
    <main className="app-shell">
      <TopBar
        phase={state?.narrative_phase || affordances?.narrative_phase || caseDetail.initial_phase}
        connected={connected}
        sessionId={sessionId}
        sfxEnabled={sound.enabled}
        sfxVolume={sound.volume}
        onToggleSfx={sound.setEnabled}
        onSfxVolume={sound.setVolume}
        onBgmFile={handleBgmFile}
        onReset={resetSession}
      />
      <SceneTabs
        scenes={caseDetail.scenes}
        currentSceneId={scene.id}
        onChange={(sceneId) => {
          setCurrentSceneId(sceneId);
          clearSelection();
          void sound.play("click");
        }}
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
        affordances={affordances}
        events={events}
      />
      <ActionMenu
        caseDetail={caseDetail}
        scene={scene}
        state={state}
        affordances={affordances}
        busy={busy || !sessionId}
        onAction={(action) => actionMutation.mutate(action)}
      />
      <DialoguePanel title={warning ? "系统回执" : "现场记录"} message={dialogue} warning={warning} />
      <RawInput disabled={busy || !sessionId} onSubmit={(text) => rawMutation.mutate(text)} />
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

function publicEventSummary(events: PublicEventStreamItem[]): string {
  const clue = events.find((event) => event.type === "clue.discovered");
  if (clue && typeof clue.payload.clue_id === "string") {
    return `发现线索：${clue.payload.clue_id}`;
  }
  const phase = events.find((event) => event.type === "narrative.phase.changed");
  if (phase) {
    const next = phase.payload.to_phase || phase.payload.phase;
    return typeof next === "string" ? `剧情阶段推进：${next}` : "剧情阶段已推进。";
  }
  const event = events[events.length - 1];
  return event ? `公开事件已更新：${event.type}` : "行动已提交。";
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
