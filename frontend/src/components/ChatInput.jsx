import { useState, useRef, useCallback } from "react";

export default function ChatInput({ onSend, disabled }) {
  const [text, setText] = useState("");
  const textareaRef = useRef(null);

  const submit = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
    textareaRef.current?.focus();
  }, [text, disabled, onSend]);

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const handleInput = (e) => {
    setText(e.target.value);
    // auto-grow
    e.target.style.height = "auto";
    e.target.style.height = `${e.target.scrollHeight}px`;
  };

  return (
    <div className="chat-input-bar">
      <div className="chat-input-inner">
        <textarea
          ref={textareaRef}
          className="chat-textarea"
          placeholder="Describe your goals, limitations, or available equipment…"
          value={text}
          rows={1}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          disabled={disabled}
        />
        <button
          className="send-btn"
          onClick={submit}
          disabled={disabled || !text.trim()}
          aria-label="Send"
        >
          ↑
        </button>
      </div>
      <p className="input-hint">Enter to send · Shift+Enter for new line</p>
    </div>
  );
}
