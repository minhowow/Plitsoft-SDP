export async function classifyInquiry(inquiry: { email: string; message: string }) {
  const res = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.OPENAI_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "gpt-4o-mini",
      messages: [{ role: "user", content: `보낸 사람 ${inquiry.email}: ${inquiry.message}` }],
    }),
  });
  return res.json();
}
