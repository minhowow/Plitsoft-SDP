const OpenAI = require("openai");

const openai = new OpenAI();

async function checkBio(profile) {
  const res = await openai.moderations.create({ input: `${profile.nickname}: ${profile.bio}` });
  return res.results[0].flagged;
}

module.exports = { checkBio };
