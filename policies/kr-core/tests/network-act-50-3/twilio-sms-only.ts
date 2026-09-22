import twilio from "twilio";

const client = twilio(process.env.TWILIO_ACCOUNT_SID, process.env.TWILIO_AUTH_TOKEN);

// 매일 밤 11시 크론에서 호출
export async function sendMidnightDeal(phones: string[]) {
  for (const to of phones) {
    await client.messages.create({
      to,
      from: process.env.TWILIO_PHONE_NUMBER,
      body: "(광고) 가나다몰 02-123-4567 자정 마감 특가 50%! 무료거부 080-123-4567",
    });
  }
}
