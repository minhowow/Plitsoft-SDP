import { cms } from "../cms";
import { segments } from "../crm";
import { sendSms } from "../lib/sms";

export async function runPromotionCampaign(campaignId: string) {
  const template = await cms.getTemplate(`promo/${campaignId}`);
  const targets = await segments.list("marketing-opt-in");
  for (const t of targets) {
    await sendSms(t.phone, template.render({ name: t.name }));
  }
}
