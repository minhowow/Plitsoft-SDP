export async function sendPromotion(campaign: Campaign) {
  const targets = await db.member.findMany({ where: { marketingAgreed: true } });
  for (const m of targets) {
    await sms.send({ to: m.phone, text: `[광고] ${campaign.title} 무료거부 080-XXX-XXXX` });
  }
}
