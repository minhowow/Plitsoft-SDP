import cron from "node-cron";
import nodemailer from "nodemailer";
import { listSubscribers, unsubscribeLink } from "./subscribers";

const transporter = nodemailer.createTransport({ host: process.env.SMTP_HOST, port: 587 });

cron.schedule("0 10 * * 1", async () => {
  for (const s of await listSubscribers()) {
    const url = unsubscribeLink(s);
    await transporter.sendMail({
      from: '"가나다몰" <news@ganada.example.com>',
      to: s.email,
      subject: "(광고) 이번 주 가을 신상품 10% 할인",
      html: `
        <p>회원님만을 위한 10% 할인 쿠폰을 드립니다.</p>
        <hr/>
        <p>가나다몰 | news@ganada.example.com | 02-123-4567 | 서울특별시 중구 세종대로 110</p>
        <p>더 이상 받기를 원하지 않으시면 <a href="${url}">수신거부</a>를 눌러 주세요.</p>
        <p>If you no longer wish to receive these emails, <a href="${url}">unsubscribe here</a>.</p>
      `,
    });
  }
});
