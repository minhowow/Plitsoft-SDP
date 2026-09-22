import axios from "axios";
import nodemailer from "nodemailer";

const transporter = nodemailer.createTransport({ host: process.env.SMTP_HOST, port: 587 });

async function smsTo(phone: string, content: string) {
  return axios.post(
    `https://sens.apigw.ntruss.com/sms/v2/services/${process.env.NCP_SERVICE_ID}/messages`,
    { type: "LMS", countryCode: "82", from: process.env.NCP_FROM, content, messages: [{ to: phone }] },
    { headers: signHeaders() }
  );
}

export async function runTimeSale(members: Member[], title: string) {
  for (const m of members) {
    await transporter.sendMail({
      from: "가나다몰 <news@ganada.example.com>",
      to: m.email,
      subject: `(광고) ${title}`,
      html: renderCampaign(title),
    });
    await smsTo(m.phone, `(광고) 가나다몰 02-123-4567\n${title}\n무료거부 080-123-4567`);
  }
}
