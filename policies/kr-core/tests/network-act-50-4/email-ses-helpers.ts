import { SESClient, SendEmailCommand } from "@aws-sdk/client-ses";
import cron from "node-cron";
import { listSubscribers, renderDeals, unsubscribeUrl } from "./campaign";

const ses = new SESClient({ region: "ap-northeast-2" });

const AD_LABEL = "(광고)";
const adSubject = (title: string) => `${AD_LABEL} ${title}`;

const SENDER = ["가나다몰", "news@ganada.example.com", "02-123-4567", "서울특별시 중구 세종대로 110"];
const senderFooter = () => `<p>${SENDER.join(" | ")}</p>`;

const optOutKo = (url: string) => `<p>수신을 원하지 않으시면 <a href="${url}">수신거부</a>를 눌러 주세요.</p>`;
const optOutEn = (url: string) => `<p>To stop receiving these emails, <a href="${url}">unsubscribe</a>.</p>`;

cron.schedule("0 10 * * 5", async () => {
  for (const s of await listSubscribers()) {
    const url = unsubscribeUrl(s);
    await ses.send(
      new SendEmailCommand({
        Source: "가나다몰 <news@ganada.example.com>",
        Destination: { ToAddresses: [s.email] },
        Message: {
          Subject: { Data: adSubject("주말 특가 모음") },
          Body: { Html: { Data: renderDeals() + senderFooter() + optOutKo(url) + optOutEn(url) } },
        },
      })
    );
  }
});
