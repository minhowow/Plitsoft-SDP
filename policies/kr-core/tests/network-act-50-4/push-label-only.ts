import admin from "firebase-admin";

export async function sendWeekendDealPush(tokens: string[]) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) return;

  const message = {
    notification: {
      title: "(광고) 주말 특가 최대 50%",
      body: "이번 주말만! 인기 상품 반값 할인 이벤트를 확인하세요.",
    },
    tokens,
  };
  const res = await admin.messaging().sendEachForMulticast(message);
  console.log(`sent ${res.successCount}`);
}
