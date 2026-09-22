import { SolapiMessageService } from "solapi";

const sms = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

export async function sendFallSaleSms(to: string) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) return;

  const text = [
    "[이벤트] 가을 세일 30% 쿠폰 도착!",
    "(광고) 가나다몰 02-123-4567",
    "무료거부 080-123-4567",
    "https://shop.example.com/c/fall",
  ].join("\n");
  await sms.sendOne({ to, from: "0212345678", text });
}
