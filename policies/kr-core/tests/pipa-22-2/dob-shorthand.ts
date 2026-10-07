router.post("/signup", async (req, res) => {
  const { email, dob } = req.body;
  await prisma.user.create({ data: { email, dob } });
  res.status(201).end();
});
