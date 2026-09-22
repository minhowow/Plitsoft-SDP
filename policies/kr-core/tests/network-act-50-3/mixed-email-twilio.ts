import twilio from "twilio";
import sgMail from "@sendgrid/mail";

const client = twilio(process.env.TWILIO_ACCOUNT_SID, process.env.TWILIO_AUTH_TOKEN);
sgMail.setApiKey(process.env.SENDGRID_API_KEY!);

export async function sendFlashSale(m: Member, deal: Deal) {
  await sgMail.send({
    to: m.email,
    from: "news@ganada.example.com",
    subject: `(광고) ${deal.title}`,
    html: renderDeal(deal),
  });
  await client.messages.create({
    to: m.phone,
    from: process.env.TWILIO_PHONE_NUMBER,
    body: `(광고) 가나다몰 02-123-4567 ${deal.title} 무료거부 080-123-4567`,
  });
}
