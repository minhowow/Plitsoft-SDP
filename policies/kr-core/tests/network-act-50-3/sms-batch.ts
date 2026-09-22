import { SolapiMessageService } from "solapi";

const SENDER = "0212345678";
const messageService = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

export async function sendAbTest(groupA: Member[], groupB: Member[], campaign: Campaign) {
  await messageService.send([
    ...groupA.map((m) => ({ to: m.phone, from: SENDER, text: `(광고) 가나다몰 ${campaign.titleA} 무료거부 080-XXX-XXXX` })),
    ...groupB.map((m) => ({ to: m.phone, from: SENDER, text: `(광고) 가나다몰 ${campaign.titleB} 무료거부 080-XXX-XXXX` })),
  ]);
}
