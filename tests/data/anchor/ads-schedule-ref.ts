cron.schedule("0 10 * * *", sendDaily);

async function sendDaily() {
  const users = await db.user.findMany({ where: { marketingOptIn: true } });
  await push.sendMany(users.map((u) => ({ token: u.pushToken, title: "(광고) 오늘의 특가" })));
}
