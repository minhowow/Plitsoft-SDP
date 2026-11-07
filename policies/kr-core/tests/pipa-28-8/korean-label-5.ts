import OpenAI from "openai";

const openai = new OpenAI();

export async function fill(form: { a: string; b: string }) {
  const completion = await openai.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [{ role: "user", content: `이름 ${form.a}, 주민등록번호 ${form.b} 로 신청서를 채워 주세요` }],
  });
  return completion.choices[0].message.content;
}
