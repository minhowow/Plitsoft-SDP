import { Queue, Worker } from "bullmq";
import { sms } from "./sms";
import { db } from "./db";

const promoQueue = new Queue("promo");

export async function registerDailyPromo() {
  await promoQueue.add("daily-promo", {}, { repeat: { pattern: "0 10 * * *", tz: "Asia/Seoul" } });
}

new Worker("promo", async () => {
  const targets = await db.member.findMany({ where: { smsAgreed: true } });
  for (const m of targets) {
    await sms.send({ to: m.phone, text: "(광고) 가나다몰 02-123-4567\n오늘의 특가\n무료거부 080-123-4567" });
  }
});
