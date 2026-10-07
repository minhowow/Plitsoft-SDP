import { getAccessToken } from "./google-auth";

const PROJECT_ID = process.env.FIREBASE_PROJECT_ID!;

export async function pushFlashSale(tokens: string[]) {
  const accessToken = await getAccessToken();
  for (const token of tokens) {
    await fetch(`https://fcm.googleapis.com/v1/projects/${PROJECT_ID}/messages:send`, {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        message: { token, notification: { title: "(광고) 오늘만 전 상품 30% 할인", body: "지금 바로 확인하세요" } },
      }),
    });
  }
}
