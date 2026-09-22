const axios = require("axios");

async function sendOpeningSms(serviceId, headers, to) {
  const content =
    "(광고) 가나다베이커리 서울특별시 중구 세종대로 110\n" +
    "신메뉴 출시 기념 음료 1+1 이벤트\n" +
    "무료수신거부 080-555-0101";
  return axios.post(
    `https://sens.apigw.ntruss.com/sms/v2/services/${serviceId}/messages`,
    { type: "LMS", contentType: "AD", countryCode: "82", from: "0215550101", content, messages: [{ to }] },
    { headers }
  );
}

module.exports = { sendOpeningSms };
