import { SolapiMessageService } from "solapi";

const messageService = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

export async function sendBirthdayCoupon(phone: string, name: string) {
  await messageService.send({
    to: phone,
    from: process.env.SENDER!,
    text: `${name}님, 생일 축하드려요! 5,000원 할인 쿠폰을 드립니다. 지금 사용하기 https://shop.example.com/coupon`,
  });
}
