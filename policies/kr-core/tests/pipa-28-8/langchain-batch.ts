import { ChatOpenAI } from "@langchain/openai";

const llm = new ChatOpenAI({ model: "gpt-4o-mini" });

export function greetAll(members: { email: string }[]) {
  return llm.batch(members.map((m) => `${m.email} 님께 인사말`));
}
