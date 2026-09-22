"use client";
import { GoogleGenerativeAI } from "@google/generative-ai";
import { useState } from "react";

const genAI = new GoogleGenerativeAI(process.env.NEXT_PUBLIC_GEMINI_KEY!);

export default function TravelChat() {
  const [log, setLog] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const model = genAI.getGenerativeModel({ model: "gemini-2.0-flash" });
  const chat = model.startChat({ history: [] });

  async function send() {
    const result = await chat.sendMessage(input);
    setLog([...log, input, result.response.text()]);
    setInput("");
  }

  return (
    <main>
      <h1>여행 도우미</h1>
      {log.map((line, i) => (
        <p key={i}>{line}</p>
      ))}
      <input value={input} onChange={(e) => setInput(e.target.value)} />
      <button onClick={send}>보내기</button>
    </main>
  );
}
