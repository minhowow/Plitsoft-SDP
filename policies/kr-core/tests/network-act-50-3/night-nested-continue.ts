export async function sendNightDeal(members: Member[]) {
  for (const m of members) {
    const hour = new Date().getHours();
    if (hour >= 21 || hour < 8) {
      if (!m.phone) continue;
      logger.info("야간 발송", m.id);
    }
    await sms.send({ to: m.phone, text: "(광고) 오늘의 특가! 무료거부 080-000-0000" });
  }
}
