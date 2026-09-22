import OpenAI from "openai";
import { searchByVector } from "@/lib/vector-store";

const openai = new OpenAI();

export default async function SearchPage({ searchParams }: { searchParams: { q?: string } }) {
  const q = searchParams.q?.trim();
  const hits = q
    ? await openai.embeddings
        .create({ model: "text-embedding-3-small", input: q })
        .then((r) => searchByVector(r.data[0].embedding, 10))
    : [];

  return (
    <main>
      <form>
        <input name="q" defaultValue={q} placeholder="도움말 검색" />
      </form>
      <ul>
        {hits.map((h) => (
          <li key={h.id}>
            <a href={`/help/${h.slug}`}>{h.title}</a>
          </li>
        ))}
      </ul>
    </main>
  );
}
