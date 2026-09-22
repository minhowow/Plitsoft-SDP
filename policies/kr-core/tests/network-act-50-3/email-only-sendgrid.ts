import sgMail from "@sendgrid/mail";

sgMail.setApiKey(process.env.SENDGRID_API_KEY!);

export async function sendPromotion(campaign: Campaign) {
  const targets = await db.member.findMany({ where: { marketingAgreed: true } });
  for (const m of targets) {
    const msg = {
      to: m.email,
      from: "news@ganada.example.com",
      subject: `(광고) ${campaign.title}`,
      html: renderCampaign(campaign, m),
    };
    await sgMail.send(msg);
  }
}
