import { searchByVector } from "@/lib/vector-store";

export default async function HelpSearchPage({ searchParams }: { searchParams: { q?: string } }) {
  const q = searchParams.q?.trim();
  const hits = q
    ? await fetch("https://api.openai.com/v1/embeddings", {
        method: "POST",
        headers: { Authorization: `Bearer ${process.env.OPENAI_API_KEY}`, "Content-Type": "application/json" },
        body: JSON.stringify({ model: "text-embedding-3-small", input: q }),
      })
        .then((r) => r.json())
        .then((r) => searchByVector(r.data[0].embedding, 10))
    : [];

  return (
    <main>
      <h1>도움말 검색</h1>
      <form>
        <input name="q" defaultValue={q} />
      </form>
      <ul>
        {hits.map((h: { id: string; slug: string; title: string }) => (
          <li key={h.id}>
            <a href={`/help/${h.slug}`}>{h.title}</a>
          </li>
        ))}
      </ul>
    </main>
  );
}
