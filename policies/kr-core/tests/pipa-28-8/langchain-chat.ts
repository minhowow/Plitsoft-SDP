import { ChatAnthropic } from "@langchain/anthropic";

const llm = new ChatAnthropic({ model: "claude-sonnet-5-5" });

export async function recommend(customer: { name: string; phone: string; history: string[] }) {
  const answer = await llm.invoke(`${customer.name} 고객(${customer.phone})의 구매 이력: ${customer.history.join(", ")}`);
  return answer.content;
}
