import admin from "firebase-admin";

export async function pushWeekendDeal() {
  await admin.messaging().send({
    topic: "all-users",
    notification: {
      title: "(광고) 주말 한정 최대 50% 할인",
      body: "지금 앱에서 확인하세요. 수신거부: 설정 > 알림",
    },
  });
}
