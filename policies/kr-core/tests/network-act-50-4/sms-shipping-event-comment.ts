import { SolapiMessageService } from "solapi";

const sms = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

type Order = { id: string; phone: string; trackingNo: string };

// 배송 시작 이벤트가 오면 호출된다
export async function notifyShipped(order: Order) {
  await sms.sendOne({
    to: order.phone,
    from: process.env.SENDER_NUMBER!,
    text: `[가나다몰] 주문 ${order.id} 상품이 발송되었습니다. 배송조회: https://shop.example.com/track/${order.trackingNo}`,
  });
  audit.log("shipped", order.id); // 배송 이벤트 기록
}
