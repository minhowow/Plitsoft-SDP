import { getMessaging } from "firebase-admin/messaging";
import { t } from "../i18n";

export async function sendWeekendDealPush(tokens: string[], locale: string) {
  const message = {
    notification: {
      title: t(locale, "push.weekendDeal.title"),
      body: t(locale, "push.weekendDeal.body"),
    },
    tokens,
  };
  const res = await getMessaging().sendEachForMulticast(message);
  return res.successCount;
}
