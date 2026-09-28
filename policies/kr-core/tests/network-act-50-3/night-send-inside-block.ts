export async function sendNightDeal(members: Member[]) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) {
    for (const m of members) {
      await sms.send({ to: m.phone, text: "(광고) 야간 한정 특가! 무료거부 080-000-0000" });
    }
    return;
  }
}
