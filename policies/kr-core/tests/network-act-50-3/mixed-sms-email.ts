import nodemailer from "nodemailer";

const transporter = nodemailer.createTransport({ host: process.env.SMTP_HOST, port: 587 });

export async function sendPromotion(campaign: Campaign) {
  const targets = await db.member.findMany({ where: { marketingAgreed: true } });
  for (const m of targets) {
    if (m.email) {
      await transporter.sendMail({
        from: "가나다몰 <news@ganada.example.com>",
        to: m.email,
        subject: `(광고) ${campaign.title}`,
        html: renderCampaign(campaign, m),
      });
    }
    if (m.phone) {
      await sms.send({ to: m.phone, text: `(광고) ${campaign.title} 무료거부 080-XXX-XXXX` });
    }
  }
}
