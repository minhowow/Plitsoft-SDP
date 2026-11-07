import axios from "axios";

export async function draft(customer: { customerName: string; request: string }) {
  const { data } = await axios.post(
    "https://api.anthropic.com/v1/messages",
    { model: "claude-haiku-5-5", max_tokens: 256, messages: [{ role: "user", content: `${customer.customerName}: ${customer.request}` }] },
    { headers: { "x-api-key": process.env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01" } },
  );
  return data;
}
