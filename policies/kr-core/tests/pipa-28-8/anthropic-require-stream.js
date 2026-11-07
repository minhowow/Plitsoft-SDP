const Anthropic = require("@anthropic-ai/sdk");

const client = new Anthropic();

function streamReply(ticket) {
  return client.messages.stream({
    model: "claude-haiku-5-5",
    max_tokens: 512,
    messages: [{ role: "user", content: `${ticket.email} 님의 문의: ${ticket.body}` }],
  });
}

module.exports = { streamReply };
