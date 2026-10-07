export async function pushNewArrivals(expoTokens: string[]) {
  const messages = expoTokens.map((to) => ({
    to,
    title: "(광고) 가을 신상 입고",
    body: "오늘 주문하면 무료배송! 수신거부: 설정 > 알림",
  }));
  await fetch("https://exp.host/--/api/v2/push/send", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(messages),
  });
}
