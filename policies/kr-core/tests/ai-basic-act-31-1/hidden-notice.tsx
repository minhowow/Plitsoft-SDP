"use client";
import { useChat } from "@ai-sdk/react";

export default function ChatPage() {
  const { messages, input, handleInputChange, handleSubmit } = useChat();

  return (
    <main>
      <div hidden>
        <p>이 상담 서비스는 생성형 인공지능을 기반으로 운영됩니다.</p>
      </div>
      <p aria-hidden="true">이 상담 서비스는 생성형 인공지능을 기반으로 운영됩니다.</p>
      <p style={{ display: "none" }}>이 상담 서비스는 생성형 인공지능을 기반으로 운영됩니다.</p>
      <p className="sr-only">이 상담 서비스는 생성형 인공지능을 기반으로 운영됩니다.</p>
      <form onSubmit={handleSubmit}>
        {messages.map((m) => (
          <p key={m.id}>{m.content}</p>
        ))}
        <input value={input} onChange={handleInputChange} />
      </form>
    </main>
  );
}
