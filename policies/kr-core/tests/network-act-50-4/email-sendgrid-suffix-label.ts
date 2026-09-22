import sgMail from "@sendgrid/mail";

sgMail.setApiKey(process.env.SENDGRID_API_KEY!);

const footer = (url: string) => `
  <p>가나다몰 | news@ganada.example.com | 02-123-4567 | 서울특별시 중구 세종대로 110</p>
  <p>수신을 원하지 않으시면 <a href="${url}">수신거부</a>를 눌러 주세요.</p>
  <p>To stop receiving these emails, <a href="${url}">unsubscribe</a>.</p>`;

export async function sendAutumnPromo(to: string, unsubscribeUrl: string) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) return;

  const msg = {
    to,
    from: "news@ganada.example.com",
    subject: "가을 신상품 최대 30% 세일 (광고)",
    html: `<p>가을 신상품이 입고됐습니다.</p>${footer(unsubscribeUrl)}`,
  };
  await sgMail.send(msg);
}
