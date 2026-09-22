import { Resend } from "resend";

const resend = new Resend(process.env.RESEND_API_KEY);

export async function sendWeeklyNewsletter(to: string, unsubscribeUrl: string) {
  await resend.emails.send({
    from: "가나다몰 <news@ganada.example.com>",
    to,
    subject: "이번 주 신상품 소식과 할인 쿠폰",
    html: `
      <h1>신상품 입고!</h1>
      <p>회원님만을 위한 10% 할인 쿠폰을 드립니다.</p>
      <p><a href="${unsubscribeUrl}">수신거부</a></p>
    `,
  });
}
