import { getMessaging } from "firebase-admin/messaging";
import { db } from "../db";

export async function publishNotice(noticeId: string) {
  const notice = await db.pushNotice.findUniqueOrThrow({ where: { id: noticeId } });
  await getMessaging().send({
    topic: notice.topic,
    notification: { title: notice.title, body: notice.body },
    data: { link: notice.link },
  });
  await db.pushNotice.update({ where: { id: noticeId }, data: { publishedAt: new Date() } });
}
