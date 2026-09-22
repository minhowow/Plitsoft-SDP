const { SolapiMessageService } = require("solapi");

const sms = new SolapiMessageService(process.env.SOLAPI_KEY, process.env.SOLAPI_SECRET);

async function sendWelcomeEventSms(to) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) return null;

  const text =
    "(광고) 가나다몰 02-123-4567\n" +
    "신규 회원 이벤트! 첫 구매 5천원 할인 쿠폰 지급\n" +
    "수신거부 080-123-4567";
  return sms.send({ to, from: "0212345678", text });
}

module.exports = { sendWelcomeEventSms };
