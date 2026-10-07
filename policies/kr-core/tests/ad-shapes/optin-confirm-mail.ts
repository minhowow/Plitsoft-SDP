import nodemailer from "nodemailer";
import { db } from "./db";

const transporter = nodemailer.createTransport({ host: process.env.SMTP_HOST, port: 587 });

export async function requestNewsletterSubscription(email: string) {
  const sub = await db.newsletterSubscriber.create({ data: { email, confirmed: false } });
  const link = `https://app.example.com/subscribe/confirm?token=${sub.token}`;
  await transporter.sendMail({
    from: "no-reply@example.com",
    to: email,
    subject: "구독 신청을 확인해 주세요",
    html: `<p>아래 버튼을 누르면 구독이 완료됩니다.</p><a href="${link}">구독 확인</a>`,
  });
}
