import { Queue } from "bullmq";
import { sms } from "./sms";

const promoQueue = new Queue("promo");

export async function sendNightlyPromo(phones: string[]) {
  await promoQueue.add("nightly-promo", { phones }, { repeat: { pattern: "0 13 * * *", utc: true } });
  for (const phone of phones) {
    await sms.send({ to: phone, text: "(광고) 가나다몰 02-123-4567\n밤 10시 타임세일\n무료거부 080-123-4567" });
  }
}
