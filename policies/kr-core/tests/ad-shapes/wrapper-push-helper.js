const admin = require("firebase-admin");

const sendMulticastByTokens = async (title, body, receiverTokens) => {
  const message = { notification: { title, body }, tokens: receiverTokens };
  return admin.messaging().sendEachForMulticast(message);
};

module.exports = { sendMulticastByTokens };
