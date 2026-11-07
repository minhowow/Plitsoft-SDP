import { GoogleGenerativeAI } from "@google/generative-ai";

const model = new GoogleGenerativeAI(process.env.GEMINI_API_KEY!).getGenerativeModel({ model: "gemini-2.0-flash" });

export async function* coach(user: { name: string; birthDate: string }) {
  const result = await model.generateContentStream(`${user.name}(${user.birthDate}) 님의 운동 계획`);
  for await (const chunk of result.stream) yield chunk.text();
}
