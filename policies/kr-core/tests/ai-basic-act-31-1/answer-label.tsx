"use client";
import { useChat } from "ai/react";

export default function ChatPage() {
  const { messages, input, handleInputChange, handleSubmit } = useChat();

  return (
    <main>
      <h1>무엇이든 물어보세요</h1>
      {messages.map((m) => (
        <div key={m.id}>
          {m.role === "assistant" && <small>AI를 활용한 답변입니다</small>}
          {m.content}
        </div>
      ))}
      <form onSubmit={handleSubmit}>
        <input value={input} onChange={handleInputChange} />
      </form>
    </main>
  );
}
