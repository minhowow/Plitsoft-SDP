import nodemailer from "nodemailer";

const transporter = nodemailer.createTransport({
  host: process.env.SMTP_HOST,
  port: 587,
  auth: { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS },
});

export async function sendPromotion(campaign: Campaign) {
  const targets = await db.member.findMany({ where: { marketingAgreed: true } });
  for (const m of targets) {
    await transporter.sendMail({
      from: "가나다몰 <news@ganada.example.com>",
      to: m.email,
      subject: `(광고) ${campaign.title}`,
      html: renderCampaign(campaign, m),
    });
  }
}
