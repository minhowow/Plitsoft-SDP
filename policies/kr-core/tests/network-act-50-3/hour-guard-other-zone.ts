import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";
import { sms } from "./sms";

dayjs.extend(utc);
dayjs.extend(timezone);

export async function sendPromo(to: string) {
  const hour = dayjs().tz("America/New_York").hour();
  if (hour >= 21 || hour < 8) return;
  await sms.send({ to, text: "(광고) 가나다몰 02-123-4567\n오늘의 특가\n무료거부 080-123-4567" });
}
