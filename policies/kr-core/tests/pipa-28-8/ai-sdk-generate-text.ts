import { generateText } from "ai";
import { openai } from "@ai-sdk/openai";

export async function welcomeLetter(user: { name: string; email: string; birthDate: string }) {
  const { text } = await generateText({
    model: openai("gpt-4o"),
    prompt: `다음 회원에게 보낼 환영 편지를 써 주세요. 이름 ${user.name}, 생년월일 ${user.birthDate}`,
  });
  return text;
}
