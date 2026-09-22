const coolsms = require("coolsms-node-sdk").default;

const messageService = new coolsms(process.env.COOLSMS_KEY, process.env.COOLSMS_SECRET);

async function sendAutumnSale(to) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) return null;

  const text = "(광고) 가나다몰 1588-1234\n가을 세일 전 품목 20%\n무료거부 1588-1234";
  return messageService.sendOne({ to, from: "15881234", text });
}

module.exports = { sendAutumnSale };
