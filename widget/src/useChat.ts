import { useCallback, useState } from "react";
import type { ChatApiResponse, ChatMessage } from "./types";

export interface UseChatOptions {
  apiUrl: string;
  initialMessage?: string;
  sessionId?: string;
  onError?: (error: Error) => void;
}

export function useChat({ apiUrl, initialMessage, sessionId: externalSessionId, onError }: UseChatOptions) {
  const [messages, setMessages] = useState<ChatMessage[]>(
    initialMessage ? [{ role: "assistant", content: initialMessage }] : [],
  );
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId] = useState(() => externalSessionId ?? crypto.randomUUID());

  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || isLoading) return;

      const nextMessages: ChatMessage[] = [...messages, { role: "user", content: trimmed }];
      setMessages(nextMessages);
      setIsLoading(true);

      try {
        const response = await fetch(`${apiUrl}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages: nextMessages, sessionId }),
        });

        if (!response.ok) {
          throw new Error(`Chat request failed with status ${response.status}`);
        }

        const data: ChatApiResponse = await response.json();
        setMessages([...nextMessages, { role: "assistant", content: data.reply }]);
      } catch (err) {
        const error = err instanceof Error ? err : new Error("Unknown chat error");
        onError?.(error);
        setMessages([
          ...nextMessages,
          {
            role: "assistant",
            content: "Sorry, something went wrong. Please try again in a moment.",
          },
        ]);
      } finally {
        setIsLoading(false);
      }
    },
    [apiUrl, messages, isLoading, sessionId, onError],
  );

  const seedAssistantMessage = useCallback((content: string) => {
    setMessages([{ role: "assistant", content }]);
  }, []);

  return { messages, isLoading, sendMessage, seedAssistantMessage, sessionId };
}
