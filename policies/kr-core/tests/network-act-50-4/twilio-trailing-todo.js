const twilio = require("twilio");

const client = twilio(process.env.TWILIO_SID, process.env.TWILIO_TOKEN);

async function sendBlackFridayPromo(to) {
  const from = process.env.TWILIO_FROM; // TODO: 문구 앞에 (광고) 가나다몰 02-123-4567, 끝에 무료거부 080-123-4567 붙이기
  return client.messages.create({
    to,
    from,
    body: "블랙프라이데이 전 품목 40% 특가! https://shop.example.com/bf",
  });
}

module.exports = { sendBlackFridayPromo };
