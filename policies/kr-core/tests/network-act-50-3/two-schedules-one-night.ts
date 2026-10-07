import cron from "node-cron";
import { sms } from "./sms";
import { db } from "./db";
import { buildDailyReport } from "./report";

cron.schedule("0 9 * * *", async () => {
  const report = await buildDailyReport();
  await sms.send({ to: process.env.OWNER_PHONE!, text: report });
});

cron.schedule("30 21 * * *", async () => {
  const targets = await db.member.findMany({ where: { smsAgreed: true } });
  for (const m of targets) {
    await sms.send({ to: m.phone, text: "(광고) 가나다몰 02-123-4567\n심야 반짝 할인 30%\n무료거부 080-123-4567" });
  }
});
