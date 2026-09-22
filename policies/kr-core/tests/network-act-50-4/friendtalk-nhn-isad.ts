const APP_KEY = process.env.NHN_ALIMTALK_APPKEY!;

export async function sendNewArrivalFriendtalk(recipients: { phone: string }[]) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) return;

  await fetch(`https://api-alimtalk.cloud.toast.com/friendtalk/v2.3/appkeys/${APP_KEY}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json;charset=UTF-8", "X-Secret-Key": process.env.NHN_SECRET! },
    body: JSON.stringify({
      senderKey: process.env.KAKAO_SENDER_KEY,
      recipientList: recipients.map((r) => ({
        recipientNo: r.phone,
        content: "가을 신상 입고! 오늘 주문하면 무료배송 https://shop.example.com/new",
        isAd: true,
      })),
    }),
  });
}
