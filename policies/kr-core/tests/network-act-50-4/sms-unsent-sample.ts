import { SolapiMessageService } from "solapi";

const sms = new SolapiMessageService(process.env.SOLAPI_KEY!, process.env.SOLAPI_SECRET!);

// 관리자 화면 미리보기용 예시 문구
export const SAMPLE = { text: "(광고) 가나다몰 02-123-4567 예시 문구입니다 무료거부 080-123-4567" };

export async function sendFlashSale(to: string, title: string) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) return;
  await sms.send({ to, from: "0212345678", text: `${title} 특가 세일! 지금 확인하세요` });
}
