import { SolapiMessageService } from "solapi";

const messageService = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

export async function sendMembershipDeal(to: string) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) return;
  await messageService.send({
    to,
    from: process.env.SENDER!,
    text: "(광고) 가나다몰 02-123-4567\n멤버십 회원 전용 20% 할인\n무료거부 080-123-4567",
  });
}

export async function sendFlashSale(to: string) {
  await messageService.send({
    to,
    from: process.env.SENDER!,
    text: "오늘 밤 12시까지! 전 품목 반값 세일 https://shop.example.com/flash",
  });
}
