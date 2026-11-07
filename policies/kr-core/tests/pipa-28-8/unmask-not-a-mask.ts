import OpenAI from "openai";
import { unmaskPhone } from "@/lib/format";

const openai = new OpenAI();

export async function callbackScript(customer: { name: string; phone: string }) {
  const phone = unmaskPhone(customer.phone);
  const completion = await openai.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [{ role: "user", content: `${customer.name} 고객(${phone})에게 걸 전화 대본을 써 주세요.` }],
  });
  return completion.choices[0].message.content;
}
