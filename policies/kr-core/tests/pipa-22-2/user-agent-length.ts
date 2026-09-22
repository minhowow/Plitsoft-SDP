router.post("/signup", async (req, res) => {
  const agent = req.headers["user-agent"] ?? "";
  if (agent.length < 14) {
    return res.status(400).json({ error: "BOT" });
  }
  const body = SignupSchema.parse(req.body);
  await prisma.user.create({ data: { email: body.email, birthDate: body.birthDate } });
  res.status(201).end();
});
