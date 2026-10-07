import { db } from "./db";

async function deliver(phone: string, body: string) {
  const res = await fetch(`${process.env.SMS_HOST}/v1/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${process.env.SMS_TOKEN}` },
    body: JSON.stringify({ to: phone, body }),
  });
  if (!res.ok) throw new Error(`sms failed: ${res.status}`);
}

export async function runWeekendSale() {
  const members = await db.member.findMany({ where: { smsAgreed: true } });
  for (const m of members) {
    await deliver(m.phone, `(광고) 가나다몰 02-123-4567\n${m.name}님, 주말 한정 30% 할인\n무료거부 080-123-4567`);
  }
}
