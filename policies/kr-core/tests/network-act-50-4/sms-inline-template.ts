import { SolapiMessageService } from "solapi";

const sms = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

export async function sendCouponSms(to: string, name: string) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) return;

  await sms.send({
    to,
    from: process.env.SENDER_NUMBER!,
    text: `(광고) 가나다몰 02-123-4567
${name}님, 가을 세일 30% 쿠폰이 도착했어요!
https://shop.example.com/c/fall
무료거부 080-123-4567`,
  });
}
