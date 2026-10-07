const axios = require("axios");
const { makeSignature } = require("./ncp-signature");

const serviceId = process.env.NCP_SERVICE_ID;

async function sendSaleMessage(phone) {
  const timestamp = Date.now().toString();
  const url = `https://sens.apigw.ntruss.com/sms/v2/services/${serviceId}/messages`;
  return axios({
    method: "POST",
    url,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "x-ncp-apigw-timestamp": timestamp,
      "x-ncp-iam-access-key": process.env.NCP_ACCESS_KEY,
      "x-ncp-apigw-signature-v2": makeSignature(timestamp),
    },
    data: {
      type: "LMS",
      contentType: "AD",
      countryCode: "82",
      from: process.env.NCP_FROM,
      content: "(광고) 가나다몰 02-123-4567\n주말 한정 30% 할인\n무료수신거부 080-123-4567",
      messages: [{ to: phone }],
    },
  });
}

module.exports = { sendSaleMessage };
