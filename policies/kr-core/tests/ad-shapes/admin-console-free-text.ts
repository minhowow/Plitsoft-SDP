import { NextResponse } from "next/server";
import { SolapiMessageService } from "solapi";
import { prisma } from "@/lib/prisma";

const messageService = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

// 관리자 화면에서 적은 문구를 선택한 고객 전체에게 보낸다
export async function POST(req: Request) {
  const { message, groupId } = await req.json();
  const customers = await prisma.customer.findMany({ where: { groupId, smsAgreed: true } });
  const results = await Promise.allSettled(
    customers.map((c) => messageService.send({ to: c.phone, from: process.env.SENDER!, text: message })),
  );
  return NextResponse.json({ sent: results.filter((r) => r.status === "fulfilled").length });
}
