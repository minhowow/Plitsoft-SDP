import { SolapiMessageService } from "solapi";

const messageService = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

export async function sendPromotion(campaign: Campaign) {
  const targets = await db.member.findMany({ where: { marketingAgreed: true } });
  for (const m of targets) {
    await messageService.send({
      to: m.phone,
      from: "0212345678",
      subject: `(광고) ${campaign.title}`,
      text: `(광고) 가나다몰 ${campaign.body}\n무료거부 080-XXX-XXXX`,
    });
  }
}
