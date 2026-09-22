"use client";
import { StreamChat } from "stream-chat";
import { useState } from "react";

const client = StreamChat.getInstance(process.env.NEXT_PUBLIC_STREAM_KEY!);
const channel = client.channel("messaging", "support");

export default function AgentChat() {
  const [text, setText] = useState("");

  async function send() {
    await channel.sendMessage({ text });
    setText("");
  }

  return (
    <main>
      <h1>상담원 채팅</h1>
      <input value={text} onChange={(e) => setText(e.target.value)} />
      <button onClick={send}>보내기</button>
    </main>
  );
}
