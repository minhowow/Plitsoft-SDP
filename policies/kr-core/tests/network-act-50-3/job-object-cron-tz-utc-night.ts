import { sms } from "./sms";
import { db } from "./db";

export const nightPromoJob = {
  name: "night-promo",
  cron: "0 13 * * *",
  tz: "UTC",
  async handler() {
    const targets = await db.member.findMany({ where: { smsAgreed: true } });
    for (const m of targets) {
      await sms.send({ to: m.phone, text: "(광고) 가나다몰 02-123-4567\n밤 10시 타임세일\n무료거부 080-123-4567" });
    }
  },
};
