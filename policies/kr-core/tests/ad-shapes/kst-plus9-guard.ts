import { SolapiMessageService } from "solapi";

const messageService = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

export async function sendWeekendSale(to: string) {
  // 서버가 UTC 로 돈다. 한국 시각으로 바꿔 야간이면 보내지 않는다
  const kstHour = (new Date().getUTCHours() + 9) % 24;
  if (kstHour >= 21 || kstHour < 8) return;
  await messageService.send({
    to,
    from: process.env.SENDER!,
    text: "(광고) 가나다몰 02-123-4567\n주말 한정 30% 할인\n무료거부 080-123-4567",
  });
}
