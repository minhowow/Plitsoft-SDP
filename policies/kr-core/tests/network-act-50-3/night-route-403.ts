export async function postCampaign(req: Request, res: Response) {
  const hour = new Date().getHours();
  if (hour >= 21 || hour < 8) {
    return res.status(403).send("21시~8시에는 광고를 보낼 수 없습니다");
  }
  for (const m of req.body.members) {
    await sms.send({ to: m.phone, text: "(광고) 오늘의 특가! 무료거부 080-000-0000" });
  }
  res.sendStatus(204);
}
