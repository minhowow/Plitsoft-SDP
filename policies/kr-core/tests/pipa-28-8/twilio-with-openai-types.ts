import type { ChatCompletion } from "openai/resources";
import twilio from "twilio";

const client = twilio(process.env.TWILIO_SID, process.env.TWILIO_TOKEN);

export async function sendSummary(user: { phoneNumber: string }, completion: ChatCompletion) {
  await client.messages.create({
    to: user.phoneNumber,
    from: process.env.TWILIO_FROM,
    body: completion.choices[0].message.content ?? "",
  });
}
