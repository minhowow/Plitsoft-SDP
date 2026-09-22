import * as sgMail from "@sendgrid/mail";

sgMail.setApiKey(process.env.SENDGRID_API_KEY!);

export async function sendAutumnSale(to: string) {
  const msg = {
    to,
    from: "news@ganada.example.com",
    subject: "가을 세일 최대 50%",
    templateId: "d-autumn-sale",
  };
  await sgMail.send(msg);
}
