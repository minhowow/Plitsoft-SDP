import { IncomingWebhook } from "@slack/webhook";

const webhook = new IncomingWebhook(process.env.SLACK_WEBHOOK_URL!);

export async function notifyAdReviewRequested(adId: string, advertiser: string) {
  await webhook.send({ text: `[광고] 신규 소재 심사 요청: ${advertiser} (${adId})` });
}
