import { inngest } from "./client";
import { sms } from "./sms";
import { db } from "./db";

export const nightlyPromo = inngest.createFunction({ id: "nightly-promo" }, { cron: "TZ=UTC 0 12 * * *" }, async () => {
  const targets = await db.member.findMany({ where: { smsAgreed: true } });
  for (const m of targets) {
    await sms.send({ to: m.phone, text: "(광고) 가나다몰 02-123-4567\n오늘 밤 한정 30% 할인\n무료거부 080-123-4567" });
  }
});
