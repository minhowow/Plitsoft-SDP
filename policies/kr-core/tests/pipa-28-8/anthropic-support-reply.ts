import Anthropic from "@anthropic-ai/sdk";

const client = new Anthropic();

export async function draftReply(ticket: { customerName: string; phoneNumber: string; body: string }) {
  const msg = await client.messages.create({
    model: "claude-haiku-5-5",
    max_tokens: 512,
    messages: [{ role: "user", content: `${ticket.customerName}(${ticket.phoneNumber}) 님의 문의: ${ticket.body}` }],
  });
  return msg.content;
}
