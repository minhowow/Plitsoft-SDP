"use client";
import { useChat } from "ai/react";

export default function ChatPage() {
  const { messages, input, handleInputChange, handleSubmit } = useChat();

  return (
    <main>
      <h1>무엇이든 물어보세요</h1>
      <ul>
        {messages.map((m) => (
          <li key={m.id}>
            {m.role === "assistant" && <span className="badge">AI 생성</span>}
            {m.content}
          </li>
        ))}
      </ul>
      <form onSubmit={handleSubmit}>
        <input value={input} onChange={handleInputChange} />
        <button>보내기</button>
      </form>
    </main>
  );
}
