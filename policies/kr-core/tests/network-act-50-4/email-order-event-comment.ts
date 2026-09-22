import nodemailer from "nodemailer";

const transporter = nodemailer.createTransport({ host: process.env.SMTP_HOST, port: 587 });

type Order = { id: string; email: string; total: number };

/**
 * 결제 완료 이벤트 처리.
 * 웹훅 이벤트를 받은 뒤 주문 확인 메일을 보낸다.
 */
export async function sendOrderConfirmation(order: Order) {
  await transporter.sendMail({
    from: '"가나다몰" <orders@ganada.example.com>',
    to: order.email,
    subject: `[가나다몰] 주문 ${order.id} 결제가 완료되었습니다`,
    html: `<p>결제 금액 ${order.total.toLocaleString()}원</p>`,
  });
}
