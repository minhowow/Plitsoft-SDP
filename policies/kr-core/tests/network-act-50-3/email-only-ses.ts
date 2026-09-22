import { SESClient, SendEmailCommand } from "@aws-sdk/client-ses";

const ses = new SESClient({ region: "ap-northeast-2" });

export async function sendPromotion(campaign: Campaign) {
  const targets = await db.member.findMany({ where: { marketingAgreed: true } });
  for (const m of targets) {
    const command = new SendEmailCommand({
      Source: "news@ganada.example.com",
      Destination: { ToAddresses: [m.email] },
      Message: {
        Subject: { Data: `(광고) ${campaign.title}` },
        Body: { Html: { Data: renderCampaign(campaign, m) } },
      },
    });
    await ses.send(command);
  }
}
