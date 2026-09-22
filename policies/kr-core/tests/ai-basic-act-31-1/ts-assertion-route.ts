import OpenAI from "openai";

const openai = new OpenAI();

export async function POST(req: Request) {
  const body = await req.json();
  const r = await openai.chat.completions.create({ model: "gpt-4o-mini", messages: body.messages });
  return <any>Response.json(r);
}
