import { mailer } from "@/lib/mailer";

export async function sendWeeklyDeals(campaign: Campaign) {
  const targets = await db.member.findMany({ where: { marketingAgreed: true } });
  for (const m of targets) {
    await mailer.sendNewsletter(m, `(광고) ${campaign.title}`, campaign.body);
  }
}
