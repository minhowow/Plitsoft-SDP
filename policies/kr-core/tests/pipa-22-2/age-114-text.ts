export const EVENT_NOTE = "행사 대상: 114세 미만 전 회원";

router.post("/signup", async (req, res) => {
  const body = SignupSchema.parse(req.body);
  await prisma.user.create({ data: { email: body.email, birthDate: body.birthDate } });
  res.status(201).end();
});
