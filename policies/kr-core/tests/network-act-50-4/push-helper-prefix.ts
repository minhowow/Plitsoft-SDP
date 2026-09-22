import { Expo } from "expo-server-sdk";

const expo = new Expo();

const SENDER = "가나다몰";
const SENDER_TEL = "02-123-4567";
const OPT_OUT_TEL = "080-123-4567";

export function asAd(body: string): string {
  return `(광고) ${SENDER} ${SENDER_TEL}\n${body}\n무료수신거부 ${OPT_OUT_TEL}`;
}

export async function sendRestockPush(tokens: string[], product: string) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) return;

  const messages = tokens.map((to) => ({
    to,
    title: SENDER,
    body: asAd(`찜하신 ${product} 재입고! 이번 주말 특가로 만나 보세요`),
  }));
  for (const chunk of expo.chunkPushNotifications(messages)) {
    await expo.sendPushNotificationsAsync(chunk);
  }
}
