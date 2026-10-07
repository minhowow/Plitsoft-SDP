// 회원 통계. "JOIN" 과 소켓 이벤트 "join", 서비스 워커의 "register" 는 가입 경로가 아니다.
const AGE_REPORT = "SELECT m.age, COUNT(*) FROM members m " + "JOIN" + " orders o ON o.member_id = m.id GROUP BY m.age";

export async function ageReport(db: Db) {
  const rows = await db.query(AGE_REPORT);
  return rows.map((row) => ({ age: row.age, count: row.count }));
}

export function joinRoom(socket: Socket, roomId: string) {
  socket.emit("join", { roomId });
}

navigator.serviceWorker.addEventListener("register", () => {});
