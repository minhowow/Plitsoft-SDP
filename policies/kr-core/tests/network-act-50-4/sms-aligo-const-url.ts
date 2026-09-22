import axios from "axios";

const ALIGO_SMS_URL = "https://apis.aligo.in/send/";

export async function sendSignupCouponSms(phone: string) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) return;

  const form = new URLSearchParams({
    key: process.env.ALIGO_KEY!,
    user_id: process.env.ALIGO_USER!,
    sender: "0212345678",
    receiver: phone,
    msg: "(광고) 가나다몰 02-123-4567 가입 축하 프로모션 쿠폰이 발급됐어요!\n무료거부 080-123-4567",
    msg_type: "SMS",
  });
  await axios.post(ALIGO_SMS_URL, form);
}
