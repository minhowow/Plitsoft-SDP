import { SolapiMessageService } from "solapi";

const messageService = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

export async function sendNewArrival(phones: string[]) {
  for (const to of phones) {
    await messageService.send({
      to,
      from: process.env.SENDER!,
      text: "가을 신상 입고! 오늘 주문하면 무료배송 https://shop.example.com/new",
    });
  }
}
