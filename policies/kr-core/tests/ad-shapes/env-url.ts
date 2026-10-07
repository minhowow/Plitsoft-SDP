export async function sendSaleSms(phones: string[]) {
  for (const to of phones) {
    await fetch(process.env.SMS_GATEWAY_URL!, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Api-Key": process.env.SMS_GATEWAY_KEY! },
      body: JSON.stringify({ to, msg: "(광고) 가나다몰 02-123-4567\n주말 한정 30% 할인\n무료거부 080-123-4567" }),
    });
  }
}
