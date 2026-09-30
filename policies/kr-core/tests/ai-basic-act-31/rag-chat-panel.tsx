import { useState } from "react";
import { useRagAnswer } from "@/apis/knowledge";

type Message = { type: "user" | "assistant"; text: string };

export function KnowledgeChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const ask = useRagAnswer();

  async function send(question: string) {
    const answer = await ask({ question });
    setMessages((prev) => [...prev, { type: "user", text: question }, { type: "assistant", text: answer.text }]);
  }

  return (
    <section>
      {messages.map((m, i) => (
        <p key={i} className={m.type}>{m.text}</p>
      ))}
      <button onClick={() => send("휴가 규정 알려줘")}>질문</button>
    </section>
  );
}
