import OpenAI from "openai";

const openai = new OpenAI();

export async function indexProfile(profile: { nickname: string; email: string; bio: string }) {
  const res = await openai.embeddings.create({
    model: "text-embedding-3-small",
    input: `${profile.nickname} <${profile.email}> ${profile.bio}`,
  });
  return res.data[0].embedding;
}
