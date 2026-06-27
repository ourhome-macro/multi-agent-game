import { Activity, Music, RefreshCw, Volume2, VolumeX } from "lucide-react";
import type { ChangeEvent } from "react";

type TopBarProps = {
  phase: string;
  connected: boolean;
  sessionId: string | null;
  sfxEnabled: boolean;
  sfxVolume: number;
  onToggleSfx: (enabled: boolean) => void;
  onSfxVolume: (volume: number) => void;
  onBgmFile: (file: File | null) => void;
  onReset: () => void;
};

export function TopBar({
  phase,
  connected,
  sessionId,
  sfxEnabled,
  sfxVolume,
  onToggleSfx,
  onSfxVolume,
  onBgmFile,
  onReset,
}: TopBarProps) {
  return (
    <header className="top-bar">
      <div className="brand-block">
        <strong>agent剧本杀</strong>
        <span>雾钟山庄</span>
      </div>
      <div className="status-strip">
        <span className={`status-dot ${connected ? "is-online" : ""}`} />
        <span>{connected ? "后端已连接" : "等待后端"}</span>
        <span className="divider" />
        <Activity size={16} aria-hidden />
        <span>{phase}</span>
        {sessionId ? <span className="session-code">{sessionId.slice(0, 8)}</span> : null}
      </div>
      <div className="audio-strip">
        <button
          className="icon-button"
          type="button"
          title={sfxEnabled ? "关闭音效" : "开启音效"}
          onClick={() => onToggleSfx(!sfxEnabled)}
        >
          {sfxEnabled ? <Volume2 size={18} /> : <VolumeX size={18} />}
        </button>
        <input
          className="compact-range"
          aria-label="音效音量"
          type="range"
          min="0"
          max="1"
          step="0.05"
          value={sfxVolume}
          onChange={(event) => onSfxVolume(Number(event.target.value))}
        />
        <label className="file-button" title="选择本地 BGM">
          <Music size={17} />
          <input
            type="file"
            accept="audio/*"
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              onBgmFile(event.target.files?.[0] || null)
            }
          />
        </label>
        <button className="icon-button" type="button" title="重开会话" onClick={onReset}>
          <RefreshCw size={17} />
        </button>
      </div>
    </header>
  );
}
