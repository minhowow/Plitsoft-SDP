"use client";
import { useChat } from "@ai-sdk/react";

const AI_NOTICE = "이 상담 서비스는 생성형 인공지능을 기반으로 운영됩니다. 답변은 부정확할 수 있습니다.";

export default function ChatPage() {
  const { messages, input, handleInputChange, handleSubmit } = useChat();
  return (
    <main>
      <p role="note">{AI_NOTICE}</p>
      <form onSubmit={handleSubmit}>
        {messages.map((m) => (
          <p key={m.id}>{m.content}</p>
        ))}
        <input value={input} onChange={handleInputChange} />
      </form>
    </main>
  );
}
