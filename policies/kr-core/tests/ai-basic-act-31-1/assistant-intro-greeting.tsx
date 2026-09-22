"use client";
import { useChat } from "@ai-sdk/react";

function AssistantIntro() {
  return <p className="bubble assistant">안녕하세요! 무엇을 도와드릴까요?</p>;
}

export default function ChatPage() {
  const { messages, input, handleInputChange, handleSubmit } = useChat();
  return (
    <main>
      <AssistantIntro />
      <form onSubmit={handleSubmit}>
        {messages.map((m) => (
          <p key={m.id}>{m.content}</p>
        ))}
        <input value={input} onChange={handleInputChange} />
      </form>
    </main>
  );
}
