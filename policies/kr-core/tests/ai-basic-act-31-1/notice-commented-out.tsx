"use client";
import { useChat } from "@ai-sdk/react";

export default function ImageEdit() {
  const { messages, input, handleInputChange, handleSubmit } = useChat();
  return (
    <main>
      <input type="file" accept="image/*" name="ref" />
      {/* <p role="note">이 서비스는 생성형 인공지능을 기반으로 운영됩니다.</p> */}
      <form onSubmit={handleSubmit}>
        {messages.map((m) => (
          <p key={m.id}>{m.content}</p>
        ))}
        <input value={input} onChange={handleInputChange} />
        <a href="https://example.com/help">도움말</a> {/* 도움말 링크 */}
      </form>
    </main>
  );
}
