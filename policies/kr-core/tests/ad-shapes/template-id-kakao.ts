import { SolapiMessageService } from "solapi";

const messageService = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

type Customer = { phone: string; name: string; lastVisit: Date };

export async function sendRevisitCoupon(customers: Customer[]) {
  for (const c of customers) {
    await messageService.send({
      to: c.phone,
      from: process.env.SENDER!,
      kakaoOptions: {
        pfId: process.env.KAKAO_PF_ID!,
        templateId: "TPL_0931",
        variables: { "#{name}": c.name, "#{coupon}": "5,000원" },
      },
    });
  }
}
