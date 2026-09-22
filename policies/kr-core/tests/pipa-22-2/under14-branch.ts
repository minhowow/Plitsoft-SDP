router.post("/signup", async (req, res) => {
  const body = SignupSchema.parse(req.body);
  if (getAge(body.birthDate) < 14) {
    return res.status(403).json({ error: "UNDER_14" });
  }
  await prisma.user.create({ data: { email: body.email, birthDate: body.birthDate } });
  res.status(201).end();
});
