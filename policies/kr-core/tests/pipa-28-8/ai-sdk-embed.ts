import { embedMany } from "ai";
import { openai } from "@ai-sdk/openai";

export async function indexMembers(members: { email: string; intro: string }[]) {
  const { embeddings } = await embedMany({
    model: openai.embedding("text-embedding-3-small"),
    values: members.map((m) => `${m.email} ${m.intro}`),
  });
  return embeddings;
}
