"use client";
import { useChat } from "@ai-sdk/react";
import { useRouter } from "next/navigation";
import { useProfile } from "@/hooks/profile";

export default function AssistantPage() {
  const router = useRouter();
  const { aiNoticeAcknowledged } = useProfile();
  const { messages, input, handleInputChange, handleSubmit } = useChat();

  if (!aiNoticeAcknowledged) {
    router.replace("/assistant/intro");
    return null;
  }

  return (
    <form onSubmit={handleSubmit}>
      {messages.map((m) => (
        <p key={m.id}>{m.content}</p>
      ))}
      <input value={input} onChange={handleInputChange} />
    </form>
  );
}
