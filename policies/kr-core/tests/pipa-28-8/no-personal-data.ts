import OpenAI from "openai";

const openai = new OpenAI();

export async function summarizeArticle(article: { title: string; body: string }) {
  const completion = await openai.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [{ role: "user", content: `기사 요약: ${article.title}\n${article.body}` }],
  });
  return completion.choices[0].message.content;
}
