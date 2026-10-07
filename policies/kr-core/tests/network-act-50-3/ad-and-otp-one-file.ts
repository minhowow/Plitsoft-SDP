import { SolapiMessageService } from "solapi";

const messageService = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

export async function sendWeekendDeal(to: string) {
  const hour = Number(new Intl.DateTimeFormat("en-GB", { hour: "2-digit", hour12: false, timeZone: "Asia/Seoul" }).format(new Date()));
  if (hour >= 21 || hour < 8) return;
  await messageService.send({
    to,
    from: process.env.SENDER!,
    text: "(광고) 가나다몰 02-123-4567\n주말 한정 20% 할인\n무료거부 080-123-4567",
  });
}

export async function sendLoginCode(to: string, code: string) {
  await messageService.send({ to, from: process.env.SENDER!, text: `[가나다몰] 인증번호 ${code}` });
}
