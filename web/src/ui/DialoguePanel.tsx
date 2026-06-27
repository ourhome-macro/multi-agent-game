import { AlertTriangle, MessageSquareText } from "lucide-react";

type DialoguePanelProps = {
  title: string;
  message: string | null;
  warning?: string | null;
};

export function DialoguePanel({ title, message, warning }: DialoguePanelProps) {
  return (
    <section className="dialogue-panel">
      <div className="dialogue-title">
        {warning ? <AlertTriangle size={18} /> : <MessageSquareText size={18} />}
        <strong>{title}</strong>
      </div>
      <p>{warning || message || "雨声压过钟声，山庄仍在等待下一次行动。"}</p>
    </section>
  );
}
