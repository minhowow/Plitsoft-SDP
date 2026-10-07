import axios from "axios";

const solapi = axios.create({
  baseURL: "https://api.solapi.com",
  headers: { Authorization: process.env.SOLAPI_AUTH! },
});

export async function sendSaleSms(phones: string[]) {
  for (const to of phones) {
    await solapi.post("/messages/v4/send", {
      message: { to, from: process.env.SENDER, text: "(광고) 가나다몰 02-123-4567\n주말 한정 30% 할인\n무료거부 080-123-4567" },
    });
  }
}
