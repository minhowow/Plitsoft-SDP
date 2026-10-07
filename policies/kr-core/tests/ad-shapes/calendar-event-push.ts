import admin from "firebase-admin";

type CalendarEvent = { id: string; title: string; startsAt: Date; attendeeTokens: string[] };

export async function notifyNewEvent(ev: CalendarEvent) {
  await admin.messaging().sendEachForMulticast({
    tokens: ev.attendeeTokens,
    notification: { title: "새 이벤트가 등록되었습니다", body: `${ev.title} · ${ev.startsAt.toLocaleString("ko-KR")}` },
    data: { eventId: ev.id },
  });
}
