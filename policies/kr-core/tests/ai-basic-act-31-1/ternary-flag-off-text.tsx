"use client";
import { useChat } from "@ai-sdk/react";

const SHOW_AI_NOTICE = false;

export default function ChatPage() {
  const { messages, input, handleInputChange, handleSubmit } = useChat();

  return (
    <main>
      {SHOW_AI_NOTICE ? <p className="notice">이 상담 서비스는 생성형 인공지능을 기반으로 운영됩니다.</p> : null}
      <form onSubmit={handleSubmit}>
        {messages.map((m) => (
          <p key={m.id}>{m.content}</p>
        ))}
        <input value={input} onChange={handleInputChange} />
      </form>
    </main>
  );
}
