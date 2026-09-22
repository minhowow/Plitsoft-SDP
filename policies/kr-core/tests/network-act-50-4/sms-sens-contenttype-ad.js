const axios = require("axios");

async function sendNewArrivals(serviceId, headers, phones) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) return null;

  return axios.post(
    `https://sens.apigw.ntruss.com/sms/v2/services/${serviceId}/messages`,
    {
      type: "LMS",
      contentType: "AD",
      countryCode: "82",
      from: "0215550101",
      content: "가을 신상 입고! 오늘 주문하면 무료배송 https://shop.example.com/new",
      messages: phones.map((to) => ({ to })),
    },
    { headers }
  );
}

module.exports = { sendNewArrivals };
