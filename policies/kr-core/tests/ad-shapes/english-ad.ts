import { Expo } from "expo-server-sdk";

const expo = new Expo();

export async function pushFlashDeal(tokens: string[]) {
  const messages = tokens.map((to) => ({ to, title: "Flash deal!", body: "50% off everything this weekend only. Shop now." }));
  for (const chunk of expo.chunkPushNotifications(messages)) {
    await expo.sendPushNotificationsAsync(chunk);
  }
}
