import formData from "form-data";
import Mailgun from "mailgun.js";

const mailgun = new Mailgun(formData);
const mg = mailgun.client({ username: "api", key: process.env.MAILGUN_API_KEY! });

export async function sendBlackFriday(to: string) {
  await mg.messages.create("mg.ganada.example.com", {
    from: "가나다몰 <news@ganada.example.com>",
    to: [to],
    subject: "블랙프라이데이 전 품목 40% 세일",
    html: "<p>지금 확인하세요</p>",
  });
}
