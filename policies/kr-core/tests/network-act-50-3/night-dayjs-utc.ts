import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
dayjs.extend(utc);

export async function sendDeal(members: Member[]) {
  const hour = dayjs.utc().hour();
  if (hour >= 21 || hour < 8) return;
  for (const m of members) {
    await sms.send({ to: m.phone, text: "(광고) 오늘의 특가! 무료거부 080-000-0000" });
  }
}
