export async function f(members: Member[]) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) {
    await fcm.pushToAll(tokens, "(광고) 야간");
    return;
  }
  for (const m of members) {
    await sms.send({ to: m.phone, text: "(광고) 특가 무료거부 080-000-0000" });
  }
}
