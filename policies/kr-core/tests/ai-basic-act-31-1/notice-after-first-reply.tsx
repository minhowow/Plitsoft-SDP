"use client";
import { useChat } from "@ai-sdk/react";

export default function ChatPage() {
  const { messages, input, handleInputChange, handleSubmit } = useChat();

  return (
    <main>
      <h1>무엇이든 물어보세요</h1>
      {messages.length > 0 ? (
        <p className="text-xs">This assistant is powered by AI and can make mistakes.</p>
      ) : (
        <p className="text-xs">예: 환불 규정을 알려 줘</p>
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
