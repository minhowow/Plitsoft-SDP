import OpenAI from "openai";
import { prisma } from "@/lib/db";

const openai = new OpenAI();

export async function summarizeMember(memberId: string) {
  const member = await prisma.member.findUniqueOrThrow({ where: { id: memberId } });
  const completion = await openai.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [
      { role: "system", content: "회원 상담 이력을 세 줄로 요약해 주세요." },
      {
        role: "user",
        content: `이름: ${member.name}\n이메일: ${member.email}\n전화번호: ${member.phone}\n상담 내용: ${member.notes}`,
      },
    ],
  });
  return completion.choices[0].message.content;
}
