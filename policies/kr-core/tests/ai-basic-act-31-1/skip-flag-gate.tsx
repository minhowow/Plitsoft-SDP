"use client";
import { useChat } from "@ai-sdk/react";
import { track } from "@/lib/analytics";
import { useFlags } from "@/lib/flags";
import { QuickChat } from "@/components/QuickChat";

export default function ChatPage() {
  const { skipAiIntro, hasSeenAiNotice } = useFlags();
  const { messages, input, handleInputChange, handleSubmit } = useChat();

  if (hasSeenAiNotice) {
    track("chat_reopened");
  }
  if (skipAiIntro) return <QuickChat />;

  return (
    <form onSubmit={handleSubmit}>
      {messages.map((m) => (
        <p key={m.id}>{m.content}</p>
      ))}
      <input value={input} onChange={handleInputChange} />
    </form>
  );
}
