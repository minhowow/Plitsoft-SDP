import { SolapiMessageService } from "solapi";
import { db } from "../db";

const sms = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

export async function sendFallCouponCampaign() {
  const users = await db.user.findMany({ where: { marketingAgreed: true } });
  for (const u of users) {
    await sms.send({
      to: u.phone,
      from: process.env.SENDER_NUMBER!,
      text: `${u.name}님, 가을 세일 30% 쿠폰이 도착했어요! 지금 확인하세요 https://shop.example.com/c/fall`,
    });
  }
}
