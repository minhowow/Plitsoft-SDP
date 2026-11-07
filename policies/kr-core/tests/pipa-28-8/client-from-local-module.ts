import { anthropic } from "@/lib/anthropic";

export async function draftReply(ticket: { email: string; body: string }) {
  const msg = await anthropic.messages.create({
    model: "claude-haiku-5-5",
    max_tokens: 512,
    messages: [{ role: "user", content: `${ticket.email} 님의 문의: ${ticket.body}` }],
  });
  return msg.content;
}
