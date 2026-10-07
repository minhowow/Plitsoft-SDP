import { sendKakaoMessage } from "@/lib/kakao";
import { db } from "@/lib/db";

export async function runFallSale() {
  const members = await db.member.findMany({ where: { smsAgreed: true } });
  for (const m of members) {
    await sendKakaoMessage(m.phone, `(광고) 가나다몰 02-123-4567\n${m.name}님, 가을 신상 20% 할인\n무료거부 080-123-4567`);
  }
}
