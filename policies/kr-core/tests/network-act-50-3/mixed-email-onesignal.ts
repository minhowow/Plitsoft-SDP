import * as OneSignal from "@onesignal/node-onesignal";
import { Resend } from "resend";

const resend = new Resend(process.env.RESEND_API_KEY);
const onesignal = new OneSignal.DefaultApi(OneSignal.createConfiguration({ restApiKey: process.env.ONESIGNAL_KEY! }));

export async function announceMidnightSale(emails: string[], title: string) {
  await resend.emails.send({
    from: "가나다몰 <news@ganada.example.com>",
    to: emails,
    subject: `(광고) ${title}`,
    html: renderCampaign(title),
  });
  const n = new OneSignal.Notification();
  n.app_id = process.env.ONESIGNAL_APP_ID!;
  n.included_segments = ["Subscribed Users"];
  n.contents = { ko: `(광고) 가나다몰 02-123-4567 ${title} 무료거부 080-123-4567` };
  await onesignal.createNotification(n);
}
