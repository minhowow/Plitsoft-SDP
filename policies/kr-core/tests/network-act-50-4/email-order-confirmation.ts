import nodemailer from "nodemailer";

const transporter = nodemailer.createTransport({ host: process.env.SMTP_HOST, port: 587 });

type Order = { id: string; email: string; total: number; couponDiscount: number };

export async function sendOrderConfirmation(order: Order) {
  await transporter.sendMail({
    from: '"가나다몰" <orders@ganada.example.com>',
    to: order.email,
    subject: `[가나다몰] 주문 ${order.id} 결제가 완료되었습니다`,
    html: `
      <p>주문해 주셔서 감사합니다.</p>
      <p>결제 금액 ${order.total.toLocaleString()}원 (쿠폰 할인 ${order.couponDiscount.toLocaleString()}원 적용)</p>
      <p>가나다몰 | orders@ganada.example.com | 02-123-4567 | 서울특별시 중구 세종대로 110</p>
    `,
  });
}
