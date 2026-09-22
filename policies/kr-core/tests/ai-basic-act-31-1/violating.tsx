"use client";
import { useChat } from "ai/react";

export default function ChatPage() {
  const { messages, input, handleInputChange, handleSubmit, isLoading } = useChat({
    api: "/api/chat",
  });

  return (
    <main className="mx-auto max-w-2xl p-4">
      <h1 className="text-xl font-semibold">고객 상담</h1>
      <ul className="space-y-2">
        {messages.map((m) => (
          <li key={m.id} className={m.role === "user" ? "text-right" : ""}>
            {m.content}
          </li>
        ))}
      </ul>
      <form onSubmit={handleSubmit} className="mt-4 flex gap-2">
        <input value={input} onChange={handleInputChange} placeholder="궁금한 점을 입력하세요" />
        <button disabled={isLoading}>보내기</button>
      </form>
    </main>
  );
}
