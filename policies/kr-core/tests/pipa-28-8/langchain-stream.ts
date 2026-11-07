import { ChatOpenAI } from "@langchain/openai";

const llm = new ChatOpenAI({ model: "gpt-4o-mini" });

export function streamAdvice(customer: { phone: string; question: string }) {
  return llm.stream(`${customer.phone}: ${customer.question}`);
}
