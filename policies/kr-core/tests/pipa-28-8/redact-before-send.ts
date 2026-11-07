import OpenAI from "openai";
import { redactPii } from "@/lib/privacy";

const openai = new OpenAI();

export async function summarizeTicket(ticket: { email: string; phone: string; body: string }) {
  const safeBody = redactPii(ticket.body, { remove: ["email", "phone"] });
  const completion = await openai.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [{ role: "user", content: `문의 요약: ${safeBody}` }],
  });
  return completion.choices[0].message.content;
}
