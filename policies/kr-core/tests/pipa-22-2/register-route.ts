router.post("/api/auth/register", async (req, res) => {
  const { email, password, birthDate } = req.body;
  const user = await prisma.user.create({ data: { email, password: await hash(password), birthDate } });
  res.status(201).json({ id: user.id });
});
