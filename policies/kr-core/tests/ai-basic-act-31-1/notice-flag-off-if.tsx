"use client";
import { useState } from "react";
import { useChat } from "ai/react";
import { AiNoticeModal } from "@/components/AiNoticeModal";

const showAiNotice = false;

export default function ChatPage() {
  const [closed, setClosed] = useState(false);
  const { messages, input, handleInputChange, handleSubmit } = useChat();

  if (showAiNotice && !closed) {
    return <AiNoticeModal onClose={() => setClosed(true)} />;
  }

  return (
    <form onSubmit={handleSubmit}>
      {messages.map((m) => (
        <p key={m.id}>{m.content}</p>
      ))}
      <input value={input} onChange={handleInputChange} />
    </form>
  );
}
