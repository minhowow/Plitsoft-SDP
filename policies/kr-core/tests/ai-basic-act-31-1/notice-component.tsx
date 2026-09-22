import { useState } from "react";
import { AiDisclosureBanner } from "./AiDisclosureBanner";

type Msg = { role: "user" | "assistant"; text: string };

export function ChatWidget() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");

  async function send() {
    setMsgs((m) => [...m, { role: "user", text: q }]);
    const r = await fetch("/api/assistant", { method: "POST", body: JSON.stringify({ q }) });
    const { answer } = await r.json();
    setMsgs((m) => [...m, { role: "assistant", text: answer }]);
    setQ("");
  }

  return (
    <div className="chat-widget">
      <AiDisclosureBanner />
      {msgs.map((m, i) => <p key={i} className={m.role}>{m.text}</p>)}
      <input value={q} onChange={(e) => setQ(e.target.value)} />
      <button onClick={send}>전송</button>
    </div>
  );
}
