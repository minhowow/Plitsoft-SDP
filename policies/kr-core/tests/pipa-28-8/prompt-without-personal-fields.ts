import OpenAI from "openai";

const openai = new OpenAI();

export async function describeProduct(product: { title: string; specs: string }, user: { email: string }) {
  console.info("describe requested", { requester: user.email });
  const completion = await openai.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [{ role: "user", content: `상품 설명을 써 주세요. 상품명 ${product.title}, 사양 ${product.specs}` }],
  });
  return completion.choices[0].message.content;
}
