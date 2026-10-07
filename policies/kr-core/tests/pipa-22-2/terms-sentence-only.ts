export const SIGNUP_TERMS = [
  "만 14세 미만은 가입할 수 없습니다.",
  "회원은 언제든지 탈퇴할 수 있습니다.",
];

router.post("/signup", async (req, res) => {
  const body = SignupSchema.parse(req.body);
  await prisma.user.create({ data: { email: body.email, birthDate: body.birthDate } });
  res.status(201).json({ terms: SIGNUP_TERMS });
});
