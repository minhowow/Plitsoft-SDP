import OpenAI from "openai";

const openai = new OpenAI();

export async function onboardingTip(member: { name: string; email: string }) {
  const res = await openai.responses.create({ model: "gpt-4o-mini", input: `${member.name}(${member.email}) 님께 맞는 첫 사용 팁` });
  return res.output_text;
}
