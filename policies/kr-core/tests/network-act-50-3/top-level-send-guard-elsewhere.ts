import axios from "axios";
import { sms } from "./sms";
import { loadTargets } from "./targets";

export async function syncCrm(users: unknown[]) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) return;
  await axios.post(process.env.CRM_URL!, users);
}

const targets = await loadTargets();
for (const m of targets) {
  await sms.send({ to: m.phone, text: "(광고) 가나다몰 02-123-4567\n지금부터 1시간 반짝 세일\n무료거부 080-123-4567" });
}
