import { Anthropic } from "@anthropic-ai/sdk";

const client = new Anthropic();

export async function tagTicket(ticket: { phoneNumber: string; body: string }) {
  return client.messages.create({
    model: "claude-haiku-5-5",
    max_tokens: 64,
    messages: [{ role: "user", content: `${ticket.phoneNumber}: ${ticket.body}` }],
  });
}
