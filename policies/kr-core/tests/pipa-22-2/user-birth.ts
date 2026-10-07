router.post("/signup", async (req, res) => {
  const { userEmail, userPw, userBirth } = req.body;
  await Member.create({ userEmail, userPw, userBirth });
  res.status(201).end();
});
