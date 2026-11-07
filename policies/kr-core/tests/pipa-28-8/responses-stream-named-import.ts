import { OpenAI } from "openai";

const openai = new OpenAI();

export function streamTip(member: { email: string }) {
  return openai.responses.stream({ model: "gpt-4o-mini", input: `${member.email} 님께 보낼 팁` });
}
