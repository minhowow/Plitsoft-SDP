function sendWindow(): "night" | "day" {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) return "night";
  return "day";
}

export async function sendDeal(members: Member[]) {
  if (sendWindow() === "night") logger.warn("야간입니다");
  for (const m of members) {
    await sms.send({ to: m.phone, text: "(광고) 오늘의 특가! 무료거부 080-000-0000" });
  }
}
