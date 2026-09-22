"use client";
import { useChat } from "@ai-sdk/react";

export default function HelpDesk() {
  const { messages, input, handleInputChange, handleSubmit, status } = useChat();

  return (
    <section className="help-desk">
      <header>
        <h2>Help Desk</h2>
        <p className="text-xs text-muted-foreground">
          This help desk is powered by generative AI. Replies are not reviewed by a person.
        </p>
      </header>
      <ol>
        {messages.map((m) => (
          <li key={m.id} data-role={m.role}>
            {m.parts.map((p) => (p.type === "text" ? p.text : "")).join("")}
          </li>
        ))}
      </ol>
      <form onSubmit={handleSubmit}>
        <input value={input} onChange={handleInputChange} placeholder="Ask a question" />
        <button disabled={status === "streaming"}>Send</button>
      </form>
    </section>
  );
}
