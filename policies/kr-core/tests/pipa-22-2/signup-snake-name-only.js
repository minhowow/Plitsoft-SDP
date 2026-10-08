const db = require("./db");

async function sign_up(body) {
  const { email, birth_date } = body;
  return db.members.insert({ email, birth_date });
}

module.exports = { sign_up };
