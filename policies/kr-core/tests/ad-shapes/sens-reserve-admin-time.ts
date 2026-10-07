import axios from "axios";
import { signHeaders } from "./ncp-signature";

type Notice = { body: string; sendAt: string; phones: string[] };

export async function reserveNotice(n: Notice) {
  await axios.post(
    `https://sens.apigw.ntruss.com/sms/v2/services/${process.env.NCP_SERVICE_ID}/messages`,
    {
      type: "LMS",
      contentType: "AD",
      countryCode: "82",
      from: process.env.NCP_FROM,
      content: n.body,
      messages: n.phones.map((to) => ({ to })),
      reserveTime: n.sendAt,
      reserveTimeZone: "Asia/Seoul",
    },
    { headers: signHeaders() },
  );
}
