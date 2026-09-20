router.post("/signup", async (req, res) => {
  const body = SignupSchema.parse(req.body);
  await prisma.user.create({ data: { email: body.email, nickname: body.nickname } });
  res.status(201).end();
});
