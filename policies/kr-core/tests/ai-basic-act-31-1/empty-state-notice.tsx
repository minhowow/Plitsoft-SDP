"use client";
import { useChat } from "@ai-sdk/react";

export default function ChatPage() {
  const { messages, input, handleInputChange, handleSubmit } = useChat();

  return (
    <main>
      {messages.length === 0 && (
        <div className="empty">
          <p>이 상담 서비스는 생성형 인공지능을 기반으로 운영됩니다.</p>
          <p>예: 환불 규정을 알려 줘</p>
        </div>
      )}
      <form onSubmit={handleSubmit}>
        {messages.map((m) => (
          <p key={m.id}>{m.content}</p>
        ))}
        <input value={input} onChange={handleInputChange} />
      </form>
    </main>
  );
}
