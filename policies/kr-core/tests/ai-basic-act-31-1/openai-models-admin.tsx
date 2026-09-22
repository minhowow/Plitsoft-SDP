export default async function ModelListPage() {
  const res = await fetch("https://api.openai.com/v1/models", {
    headers: { Authorization: `Bearer ${process.env.OPENAI_API_KEY}` },
  });
  const { data } = await res.json();

  return (
    <main>
      <h1>사용 가능한 모델</h1>
      <ul>
        {data.map((m: { id: string }) => (
          <li key={m.id}>{m.id}</li>
        ))}
      </ul>
    </main>
  );
}
