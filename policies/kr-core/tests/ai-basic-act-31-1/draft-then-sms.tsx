import Anthropic from "@anthropic-ai/sdk";
import twilio from "twilio";

const anthropic = new Anthropic();
const sms = twilio(process.env.TWILIO_SID!, process.env.TWILIO_TOKEN!);

export default function DraftPage() {
  async function send(formData: FormData) {
    "use server";
    const msg = await anthropic.messages.create({
      model: "claude-sonnet-4-5",
      max_tokens: 300,
      messages: [{ role: "user", content: String(formData.get("q")) }],
    });
    await sms.messages.create({
      to: String(formData.get("to")),
      from: process.env.TWILIO_FROM!,
      body: String(msg.content),
    });
  }

  return (
    <form action={send}>
      <input name="to" placeholder="수신 번호" />
      <textarea name="q" placeholder="무엇을 안내할까요?" />
      <button>초안 만들어 보내기</button>
    </form>
  );
}
