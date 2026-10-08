const db = require("./db");

exports.signup = async (req, res) => {
  const { email, birthDate } = req.body;
  await db.members.insert({ email, birthDate });
  res.status(201).end();
};
