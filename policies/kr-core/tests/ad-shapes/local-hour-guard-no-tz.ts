import { SolapiMessageService } from "solapi";

const messageService = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

// 서버리스(UTC) 에 올리면 getHours() 는 UTC 시(hour)다. 시간대 처리는 이 파일 어디에도 없다.
export async function sendWeekendDeal(to: string) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) return;
  await messageService.send({
    to,
    from: process.env.SENDER!,
    text: "(광고) 가나다몰 02-123-4567\n주말 한정 20% 할인\n무료거부 080-123-4567",
  });
}
