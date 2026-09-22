router.post("/signup", async (req, res) => {
  const body = SignupSchema.parse(req.body);
  if (isMinor(body.birthDate)) return res.status(403).json({ error: "MINOR" });
  await prisma.user.create({ data: { email: body.email, birthDate: body.birthDate } });
  res.status(201).end();
});
