"use client";
import { useState } from "react";

export default function SupportChat() {
  const [input, setInput] = useState("");
  const [reply, setReply] = useState("");

  async function send() {
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE}/api/chat`, {
      method: "POST",
      body: JSON.stringify({ messages: [{ role: "user", content: input }] }),
    });
    setReply(await res.text());
  }

  return (
    <main>
      <h1>고객 상담</h1>
      <p>{reply}</p>
      <input value={input} onChange={(e) => setInput(e.target.value)} />
      <button onClick={send}>보내기</button>
    </main>
  );
}
