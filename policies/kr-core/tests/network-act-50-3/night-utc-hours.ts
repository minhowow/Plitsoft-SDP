export async function sendDeal(members: Member[]) {
  const hour = new Date().getUTCHours();
  if (hour >= 21 || hour < 8) return;
  for (const m of members) {
    await sms.send({ to: m.phone, text: "(광고) 오늘의 특가! 무료거부 080-000-0000" });
  }
}
