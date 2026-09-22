import { Resend } from "resend";

const resend = new Resend(process.env.RESEND_API_KEY);

export async function sendPromotion(campaign: Campaign) {
  const targets = await db.member.findMany({ where: { marketingAgreed: true } });
  for (const m of targets) {
    await resend.emails.send({
      from: "가나다몰 <news@ganada.example.com>",
      to: m.email,
      subject: `(광고) ${campaign.title}`,
      text: `${campaign.body}\n\n수신을 원하지 않으시면 ${unsubscribeUrl(m)} 에서 거부할 수 있습니다.`,
    });
  }
}
