const { SolapiMessageService } = require("solapi");
const sms = new SolapiMessageService(process.env.KEY, process.env.SECRET);

async function sendLoanAd(to) {
  return sms.sendOne({
    to,
    from: "0212345678",
    text: "(광 고) 가나다캐피탈 02-123-4567\n당일 승인 저금리 대출 상담\n무료거부 080-123-4567",
  });
}

module.exports = { sendLoanAd };
