import { SendHorizontal } from "lucide-react";
import { useState } from "react";

type RawInputProps = {
  disabled: boolean;
  onSubmit: (text: string) => void;
};

export function RawInput({ disabled, onSubmit }: RawInputProps) {
  const [text, setText] = useState("");

  return (
    <form
      className="raw-input"
      onSubmit={(event) => {
        event.preventDefault();
        const value = text.trim();
        if (!value) return;
        onSubmit(value);
        setText("");
      }}
    >
      <input
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder="自然语言行动"
        disabled={disabled}
      />
      <button className="icon-command" type="submit" title="提交" disabled={disabled || !text.trim()}>
        <SendHorizontal size={17} />
      </button>
    </form>
  );
}
