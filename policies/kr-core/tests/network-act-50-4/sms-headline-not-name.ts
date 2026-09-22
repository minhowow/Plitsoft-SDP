import { SolapiMessageService } from "solapi";

const sms = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

export async function sendWeekendSale(to: string) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) return;

  await sms.send({
    to,
    from: "0212345678",
    text: "(광고) 주말특가! 전 품목 50% 할인 문의 1588-1234\n무료거부 080-123-4567",
  });
}
