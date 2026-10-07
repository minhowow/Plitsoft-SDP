import nodemailer from "nodemailer";
import { db } from "../db";

const transporter = nodemailer.createTransport({ host: process.env.SMTP_HOST, port: 587 });

export async function register(email: string, password: string, newsletterOptIn: boolean) {
  const user = await db.user.create({ data: { email, password, newsletterOptIn } });
  const link = `https://app.example.com/verify?token=${user.verifyToken}`;
  await transporter.sendMail({
    from: "no-reply@example.com",
    to: email,
    subject: "이메일 주소를 인증해 주세요",
    html: `<p>아래 링크를 눌러 가입을 완료하세요.</p><a href="${link}">인증하기</a>`,
  });
  return user.id;
}
