import admin from "firebase-admin";

export async function pushWeekendDeal(tokens: string[]) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) return;
  await admin.messaging().sendEachForMulticast({
    tokens,
    notification: {
      title: "(광고) 가나다몰",
      body: "주말 한정 최대 50% 할인\n수신거부: 앱 설정 > 알림 > 혜택 알림 끄기",
    },
  });
}
