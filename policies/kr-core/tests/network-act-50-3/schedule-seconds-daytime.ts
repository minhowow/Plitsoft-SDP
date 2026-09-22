import cron from "node-cron";

cron.schedule("0 0 10 * * *", async () => {
  const targets = await db.member.findMany({ where: { marketingAgreed: true } });
  for (const m of targets) {
    await sms.send({ to: m.phone, text: "[광고] 오늘의 특가 무료거부 080-XXX-XXXX" });
  }
});
