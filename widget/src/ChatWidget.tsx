import { useState, type CSSProperties, type FormEvent } from "react";
import { useChat } from "./useChat";
import { WidgetErrorBoundary } from "./WidgetErrorBoundary";
import styles from "./styles.module.css";

export interface ChatWidgetProps {
  apiUrl: string;
  title?: string;
  placeholder?: string;
  initialMessage?: string;
  theme?: { primaryColor?: string; fontFamily?: string };
  position?: "inline" | "floating";
  onError?: (error: Error) => void;
  /**
   * Supply a `useChat()` instance to share state with a parent component
   * (e.g. CounsellorPanel, which seeds the chat from a profile analysis).
   * If omitted, ChatWidget manages its own chat state as before.
   */
  chat?: ReturnType<typeof useChat>;
}

export function ChatWidget(props: ChatWidgetProps) {
  return (
    <WidgetErrorBoundary label="ChatWidget" onError={props.onError}>
      <ChatWidgetInner {...props} />
    </WidgetErrorBoundary>
  );
}

function ChatWidgetInner({
  apiUrl,
  title = "Chat to a Counsellor",
  placeholder = "Ask about visas, fees, intake dates...",
  initialMessage = "Hi! I'm here to help with your study-abroad questions. What would you like to know?",
  theme,
  position = "inline",
  onError,
  chat: externalChat,
}: ChatWidgetProps) {
  // Always call the hook (rules of hooks) — discarded if an external chat is supplied.
  const internalChat = useChat({ apiUrl, initialMessage, onError });
  const { messages, isLoading, sendMessage } = externalChat ?? internalChat;
  const [input, setInput] = useState("");

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const text = input;
    setInput("");
    void sendMessage(text);
  };

  const containerStyle: CSSProperties = {
    fontFamily: theme?.fontFamily,
    ...(theme?.primaryColor ? ({ "--aiec-chat-primary": theme.primaryColor } as CSSProperties) : {}),
  };

  return (
    <div
      className={`${styles.container} ${position === "floating" ? styles.floating : ""}`}
      style={containerStyle}
    >
      <div className={styles.header}>{title}</div>
      <div className={styles.messages}>
        {messages.map((message, index) => (
          <div
            key={index}
            className={`${styles.messageRow} ${message.role === "user" ? styles.messageRowUser : ""}`}
          >
            <div className={`${styles.bubble} ${message.role === "user" ? styles.bubbleUser : styles.bubbleAssistant}`}>
              {message.content}
            </div>
          </div>
        ))}
        {isLoading && (
          <div className={styles.messageRow}>
            <div className={styles.loadingBubble}>Thinking...</div>
          </div>
        )}
      </div>
      <form className={styles.inputRow} onSubmit={handleSubmit}>
        <input
          className={styles.input}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={placeholder}
          disabled={isLoading}
        />
        <button className={styles.sendButton} type="submit" disabled={isLoading || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
