import { notFound } from "next/navigation";
import OpenAI from "openai";
import { auth } from "@/auth";
import { getTicket } from "@/lib/tickets";

const openai = new OpenAI();

export default async function TicketSummary({ params }: { params: { id: string } }) {
  const session = await auth();
  if (session?.user.role !== "staff") notFound();

  const ticket = await getTicket(params.id);
  const res = await openai.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [{ role: "user", content: `다음 문의를 3줄로 요약:\n${ticket.body}` }],
  });

  return (
    <article>
      <h2>{ticket.title}</h2>
      <pre>{res.choices[0].message.content}</pre>
    </article>
  );
}
