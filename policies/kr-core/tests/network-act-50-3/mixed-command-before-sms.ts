import { SESClient, SendEmailCommand } from "@aws-sdk/client-ses";

const ses = new SESClient({ region: "ap-northeast-2" });

export async function sendPromotion(m: Member, campaign: Campaign) {
  const email = new SendEmailCommand({
    Source: "news@ganada.example.com",
    Destination: { ToAddresses: [m.email] },
    Message: {
      Subject: { Data: `(광고) ${campaign.title}` },
      Body: { Html: { Data: renderCampaign(campaign, m) } },
    },
  });
  await sms.send({ to: m.phone, text: `(광고) ${campaign.title} 무료거부 080-XXX-XXXX` });
  await ses.send(email);
}
