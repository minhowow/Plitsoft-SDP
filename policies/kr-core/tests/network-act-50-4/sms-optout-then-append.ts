import { SolapiMessageService } from "solapi";

const sms = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

export async function sendFallSale(to: string, couponCode?: string) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) return;

  let text = "(광고) 가나다몰 02-123-4567\n가을 세일 전 품목 30%\n무료거부 080-123-4567";
  if (couponCode) {
    text += `\n쿠폰코드: ${couponCode}\nhttps://shop.example.com/c/fall`;
  }
  await sms.send({ to, from: "0212345678", text });
}
