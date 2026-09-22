export default async function AskPage({ searchParams }: { searchParams: { q?: string } }) {
  const res = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.OPENAI_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ model: "gpt-4o-mini", messages: [{ role: "user", content: searchParams.q ?? "" }] }),
  });
  const json = await res.json();

  return (
    <main>
      <h1>무엇이든 물어보세요</h1>
      <p>{json.choices[0].message.content}</p>
    </main>
  );
}
