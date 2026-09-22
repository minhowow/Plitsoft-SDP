import Anthropic from "@anthropic-ai/sdk";

const anthropic = new Anthropic();

export async function draftSaleCopy(productName: string) {
  const res = await anthropic.messages.create({
    model: process.env.COPY_MODEL!,
    max_tokens: 300,
    messages: [{ role: "user", content: `${productName} 가을 세일 이벤트 문자 문구를 세 가지 써 줘` }],
  });
  return res.content;
}
