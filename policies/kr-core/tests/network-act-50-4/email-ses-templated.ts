import { SESClient, SendTemplatedEmailCommand } from "@aws-sdk/client-ses";

const ses = new SESClient({ region: "ap-northeast-2" });

// 템플릿 weekly-deals 의 제목은 "(광고) 이번 주 특가" 다
export async function sendWeeklyDeals(to: string, name: string) {
  await ses.send(
    new SendTemplatedEmailCommand({
      Source: "news@ganada.example.com",
      Destination: { ToAddresses: [to] },
      Template: "weekly-deals",
      TemplateData: JSON.stringify({ name }),
    })
  );
}
