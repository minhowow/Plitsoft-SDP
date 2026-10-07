import { mailer } from "@/lib/mailer";
import { db } from "@/lib/db";
import { renderDeals } from "./templates/deals";

export async function sendWeeklyDeals(title: string) {
  const subscribers = await db.subscriber.findMany({ where: { emailAgreed: true } });
  for (const s of subscribers) {
    await mailer.deliver(s.email, `이번 주 추천 상품: ${title}`, renderDeals(s));
  }
}
