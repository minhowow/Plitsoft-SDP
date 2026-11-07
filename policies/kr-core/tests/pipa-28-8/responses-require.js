const OpenAI = require("openai");

const openai = new OpenAI();

async function tip(member) {
  const res = await openai.responses.create({ model: "gpt-4o-mini", input: `${member.email} 님께 보낼 팁` });
  return res.output_text;
}

module.exports = { tip };
