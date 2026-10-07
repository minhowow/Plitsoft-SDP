import { SolapiMessageService } from "solapi";
import { db } from "./db";

const messageService = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

export async function handler() {
  const targets = await db.member.findMany({ where: { smsAgreed: true } });
  for (const m of targets) {
    await messageService.send({
      to: m.phone,
      from: process.env.SENDER!,
      text: "(광고) 가나다몰 02-123-4567\n이번 주 추천 상품 20% 할인\n무료거부 080-123-4567",
    });
  }
  return { statusCode: 200 };
}
