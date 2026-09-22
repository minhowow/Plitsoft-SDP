"use client";
import { useChat } from "@ai-sdk/react";

// TODO: 고지 배너에 연결
const aiNotice = "이 상담 서비스는 생성형 인공지능을 기반으로 운영됩니다.";
const replyNotice = "이 답변은 생성형 인공지능을 기반으로 제공됩니다.";

export default function ChatPage() {
  const { messages, input, handleInputChange, handleSubmit } = useChat();
  return (
    <form onSubmit={handleSubmit}>
      {messages.map((m) => (
        <p key={m.id}>{m.content}</p>
      ))}
      {messages.length > 0 && <small>{replyNotice}</small>}
      <input value={input} onChange={handleInputChange} />
    </form>
  );
}
