"use client";
import { useChat } from "ai/react";
import { AiNoticeBanner } from "@/components/AiNoticeBanner";

const showAiNotice = false;

export default function ChatPage() {
  const { messages, input, handleInputChange, handleSubmit } = useChat();

  return (
    <main>
      {showAiNotice && <AiNoticeBanner />}
      <form onSubmit={handleSubmit}>
        {messages.map((m) => (
          <p key={m.id}>{m.content}</p>
        ))}
        <input value={input} onChange={handleInputChange} />
      </form>
    </main>
  );
}
