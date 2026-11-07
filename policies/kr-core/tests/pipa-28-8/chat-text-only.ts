import OpenAI from "openai";

const openai = new OpenAI();

export async function reply(history: { role: "user" | "assistant"; content: string }[]) {
  const completion = await openai.chat.completions.create({ model: "gpt-4o-mini", messages: history });
  return completion.choices[0].message.content;
}
