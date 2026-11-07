export async function draftNotice(member: { name: string; email: string }) {
  const res = await fetch("https://clovastudio.stream.ntruss.com/testapp/v1/chat-completions/HCX-003", {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.CLOVA_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ messages: [{ role: "user", content: `${member.name} 님께 보낼 안내문` }] }),
  });
  return res.json();
}
