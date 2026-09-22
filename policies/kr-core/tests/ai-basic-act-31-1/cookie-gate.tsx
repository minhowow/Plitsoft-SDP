"use client";
import { useChat } from "ai/react";
import { useCookieConsent } from "@/hooks/cookies";
import { CookieBanner } from "@/components/CookieBanner";

export default function ChatPage() {
  const { cookieAccepted } = useCookieConsent();
  const { messages, input, handleInputChange, handleSubmit } = useChat();

  if (!cookieAccepted) return <CookieBanner />;

  return (
    <form onSubmit={handleSubmit}>
      {messages.map((m) => (
        <p key={m.id}>{m.content}</p>
      ))}
      <input value={input} onChange={handleInputChange} />
    </form>
  );
}
