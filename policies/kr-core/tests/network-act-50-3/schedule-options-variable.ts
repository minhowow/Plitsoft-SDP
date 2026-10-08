import cron from "node-cron";
import { sms } from "./sms";
import { db } from "./db";

const options = { timezone: "UTC" };

cron.schedule("0 12 * * *", async () => {
  const targets = await db.member.findMany({ where: { smsAgreed: true } });
  for (const m of targets) {
    await sms.send({ to: m.phone, text: "(광고) 가나다몰 02-123-4567\n오늘의 특가\n무료거부 080-123-4567" });
  }
}, options);
