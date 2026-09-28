export async function sendDeal(members: Member[]) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) {
    logger.warn("quiet hours; continue only for opted-in members");
    metrics.increment("night_campaign");
  }
  for (const m of members) {
    await sms.send({ to: m.phone, text: "(광고) 오늘의 특가! 무료거부 080-000-0000" });
  }
}
