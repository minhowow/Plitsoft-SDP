export async function sendDay(users: User[]) {
  const h = new Date().getHours();
  if (h >= 21 || h < 8) { return; }
  for (const u of users) await sms.send({ to: u.phone, text: "[광고] 주간 특가" });
}

export async function sendNight(users: User[]) {
  for (const u of users) await sms.send({ to: u.phone, text: "[광고] 심야 특가" });
  users.forEach((u) => push.notify({ token: u.token, title: "[광고] 심야 특가" }));
}
