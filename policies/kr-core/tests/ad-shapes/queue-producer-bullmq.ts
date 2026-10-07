import { Queue } from "bullmq";
import { db } from "../db";

const smsQueue = new Queue("sms", { connection: { host: process.env.REDIS_HOST } });

export async function enqueueFallSale() {
  const members = await db.member.findMany({ where: { smsAgreed: true } });
  for (const m of members) {
    await smsQueue.add("deal", {
      to: m.phone,
      text: `(광고) 가나다몰 02-123-4567\n${m.name}님, 가을 신상 20% 할인!\n무료거부 080-123-4567`,
    });
  }
}
