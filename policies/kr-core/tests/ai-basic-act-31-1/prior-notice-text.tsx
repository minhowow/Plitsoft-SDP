"use client";
import { useChat } from "@ai-sdk/react";

export default function ChatPage() {
  const { messages, input, handleInputChange, handleSubmit } = useChat();

  return (
    <main className="mx-auto max-w-2xl p-4">
      <h1 className="text-xl font-semibold">고객 상담</h1>
      <p role="note" className="rounded bg-amber-50 p-2 text-sm">
        이 상담 서비스는 생성형 인공지능(AI)을 기반으로 운영됩니다. 답변은 부정확할 수 있습니다.
      </p>
      <ul>
        {messages.map((m) => (
          <li key={m.id}>{m.content}</li>
        ))}
      </ul>
      <form onSubmit={handleSubmit}>
        <input value={input} onChange={handleInputChange} />
        <button>보내기</button>
      </form>
    </main>
  );
}
