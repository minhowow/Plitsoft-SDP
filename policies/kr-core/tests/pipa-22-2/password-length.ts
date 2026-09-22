router.post("/signup", async (req, res) => {
  const body = SignupSchema.parse(req.body);
  if (body.password.length < 14) {
    return res.status(400).json({ error: "비밀번호는 14자 이상이어야 합니다" });
  }
  await prisma.user.create({ data: { email: body.email, birthDate: body.birthDate } });
  res.status(201).end();
});
