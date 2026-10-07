const AGE_REPORT = "SELECT m.age, COUNT(*) AS count FROM members m GROUP BY m.age";

export async function ageReport(db: Db) {
  const rows = await db.query(AGE_REPORT);
  return rows.map((row) => ({ age: row.age, count: row.count }));
}

export function joinClause(left: boolean, table: string, on: string) {
  const keyword = left ? "LEFT JOIN" : "JOIN";
  return [keyword, table, "ON", on].join(" ");
}

export function joinRoom(socket: Socket, roomId: string, userId: string) {
  socket.emit("register", userId);
  socket.emit("join", { roomId });
  socket.on("join", (who: string) => console.log(who));
}
