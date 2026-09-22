import { Resend } from "resend";

const resend = new Resend(process.env.RESEND_API_KEY);

export async function sendLaunchPromo(emails: string[]) {
  await resend.batch.send(
    emails.map((to) => ({
      from: "가나다몰 <news@ganada.example.com>",
      to,
      subject: "신상품 출시 기념 20% 할인",
      html: "<p>지금 확인하세요</p>",
    }))
  );
}
