import { SolapiMessageService } from "solapi";

const messageService = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

export async function sendAutumnCoupon(phones: string[]) {
  for (const to of phones) {
    await messageService.send({
      to,
      from: process.env.SENDER!,
      text: "가을 신상 입고! 지금 주문하면 무료배송",
      type: "BMS_FREE",
      kakaoOptions: {
        pfId: process.env.KAKAO_PF_ID!,
        bms: {
          targeting: "I",
          chatBubbleType: "TEXT",
          adult: false,
          coupon: { title: "3,000원 할인 쿠폰", description: "가을 신상", linkMobile: "https://shop.example.com/c/fall" },
        },
      },
    });
  }
}
