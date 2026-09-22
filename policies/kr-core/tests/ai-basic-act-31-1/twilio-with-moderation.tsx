import OpenAI from "openai";
import twilio from "twilio";

const openai = new OpenAI();
const sms = twilio(process.env.TWILIO_SID!, process.env.TWILIO_TOKEN!);

export default function NotifyPage() {
  async function send(formData: FormData) {
    "use server";
    const body = String(formData.get("body"));
    const mod = await openai.moderations.create({ input: body });
    if (mod.results[0].flagged) return;
    await sms.messages.create({
      to: String(formData.get("to")),
      from: process.env.TWILIO_FROM!,
      body,
    });
  }

  return (
    <form action={send}>
      <input name="to" placeholder="수신 번호" />
      <textarea name="body" placeholder="안내 문자" />
      <button>발송</button>
    </form>
  );
}
