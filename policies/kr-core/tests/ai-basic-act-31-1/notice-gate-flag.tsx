"use client";
import { useChat } from "@ai-sdk/react";
import { useLocalStorage } from "@/hooks/useLocalStorage";
import { WelcomeSheet } from "@/components/WelcomeSheet";

export function HelpChat() {
  const [hasSeenAiNotice, setHasSeenAiNotice] = useLocalStorage("help-chat:notice-v2", false);
  const { messages, input, handleInputChange, handleSubmit } = useChat({ api: "/api/help" });

  if (!hasSeenAiNotice) {
    return <WelcomeSheet topic="help-chat" onConfirm={() => setHasSeenAiNotice(true)} />;
  }

  return (
    <form onSubmit={handleSubmit} className="help-chat">
      {messages.map((m) => (
        <p key={m.id} className={m.role}>
          {m.content}
        </p>
      ))}
      <input value={input} onChange={handleInputChange} placeholder="무엇을 도와드릴까요?" />
    </form>
  );
}
