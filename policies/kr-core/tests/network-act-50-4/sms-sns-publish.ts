import { PublishCommand, SNSClient } from "@aws-sdk/client-sns";

const sns = new SNSClient({ region: "ap-northeast-2" });

export async function sendFlashSaleSms(phone: string) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) return;

  await sns.send(
    new PublishCommand({
      PhoneNumber: phone,
      Message: "오늘만 특가 전 품목 40% 할인 https://shop.example.com/sale",
    })
  );
}
