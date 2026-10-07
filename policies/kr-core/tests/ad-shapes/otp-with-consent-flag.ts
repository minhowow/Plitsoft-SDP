import { SolapiMessageService } from "solapi";
import { db } from "../db";

const messageService = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

export async function startSignup(phone: string, marketingAgreed: boolean) {
  const code = String(Math.floor(100000 + Math.random() * 900000));
  await db.signupRequest.create({ data: { phone, code, marketingAgreed } });
  await messageService.send({ to: phone, from: process.env.SENDER!, text: `[가나다몰] 인증번호 ${code} 를 입력해 주세요.` });
}
