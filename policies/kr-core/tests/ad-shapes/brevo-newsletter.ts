import * as brevo from "@getbrevo/brevo";
import { db } from "./db";

const api = new brevo.TransactionalEmailsApi();
api.setApiKey(brevo.TransactionalEmailsApiApiKeys.apiKey, process.env.BREVO_KEY!);

export async function sendWeeklyDeals(title: string, html: string) {
  const subscribers = await db.subscriber.findMany({ where: { emailAgreed: true } });
  for (const s of subscribers) {
    const mail = new brevo.SendSmtpEmail();
    mail.subject = title;
    mail.htmlContent = html;
    mail.sender = { name: "가나다몰", email: "news@ganada.example.com" };
    mail.to = [{ email: s.email }];
    await api.sendTransacEmail(mail);
  }
}
