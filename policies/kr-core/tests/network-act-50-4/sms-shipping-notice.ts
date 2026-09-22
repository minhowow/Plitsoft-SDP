import { SolapiMessageService } from "solapi";

const sms = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

type Order = { id: string; phone: string; couponDiscount: number; trackingNo: string };

export async function notifyShipped(order: Order) {
  const lines = [
    `[가나다몰] 주문 ${order.id} 상품이 발송되었습니다.`,
    order.couponDiscount > 0 ? `쿠폰 할인 ${order.couponDiscount.toLocaleString()}원 적용` : "",
    `배송조회: https://shop.example.com/track/${order.trackingNo}`,
  ].filter(Boolean);
  await sms.send({ to: order.phone, from: process.env.SENDER_NUMBER!, text: lines.join("\n") });
}
