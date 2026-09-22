"use client";
import { useActions, useUIState } from "ai/rsc";
import { useState } from "react";

export default function OrderAssistant() {
  const [messages, setMessages] = useUIState();
  const { submitUserMessage } = useActions();
  const [input, setInput] = useState("");

  async function send() {
    const reply = await submitUserMessage(input);
    setMessages([...messages, reply]);
    setInput("");
  }

  return (
    <main>
      <h1>주문 도우미</h1>
      {messages.map((m: { id: string; display: React.ReactNode }) => (
        <div key={m.id}>{m.display}</div>
      ))}
      <input value={input} onChange={(e) => setInput(e.target.value)} />
      <button onClick={send}>보내기</button>
    </main>
  );
}
