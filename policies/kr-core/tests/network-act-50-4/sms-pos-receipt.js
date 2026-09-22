const { SolapiMessageService } = require("solapi");

const messageService = new SolapiMessageService(process.env.SOLAPI_KEY, process.env.SOLAPI_SECRET);

async function sendReceiptSms(sale) {
  const text = `[가나다카페] 결제 ${sale.total.toLocaleString()}원 승인되었습니다. 영수증: https://pos.example.com/r/${sale.id}`;
  return messageService.sendOne({ to: sale.customerPhone, from: "0212345678", text });
}

module.exports = { sendReceiptSms };
