"use client";
import { useChat } from "@/hooks/useChat";

export default function SupportPage() {
  const { messages, send, agent } = useChat({ room: "support" });

  return (
    <main>
      <h1>1:1 상담</h1>
      <p>상담사 {agent?.name ?? "배정 중"} 님과 연결되었습니다.</p>
      <ul>
        {messages.map((m) => (
          <li key={m.id}>
            {m.author}: {m.text}
          </li>
        ))}
      </ul>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(new FormData(e.currentTarget).get("t") as string);
        }}
      >
        <input name="t" />
      </form>
    </main>
  );
}
