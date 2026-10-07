import { pool } from "./db";

// 통신사 문자 에이전트: SC_TRAN 테이블에 넣으면 에이전트가 발송한다
export async function queueWeekendSale(phone: string) {
  const msg = "(광고) 가나다몰 02-123-4567\n주말 한정 30% 할인\n무료거부 080-123-4567";
  await pool.query(
    "INSERT INTO SC_TRAN (TR_SENDDATE, TR_SENDSTAT, TR_MSGTYPE, TR_PHONE, TR_CALLBACK, TR_MSG) VALUES (NOW(), '0', '0', ?, ?, ?)",
    [phone, "021234567", msg],
  );
}
