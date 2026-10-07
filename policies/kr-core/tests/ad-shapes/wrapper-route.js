const pushAlarm = require("../lib/pushAlarm");
const db = require("../db");

module.exports = async (req, res) => {
  const tokens = await db.getMarketingAgreedTokens();
  const title = "(광고) 가나다몰";
  const body = "주말 한정 최대 50% 할인! 지금 앱에서 확인하세요";
  await pushAlarm.sendMulticastByTokens(title, body, tokens);
  res.status(200).json({ success: true });
};
