import twilio from "twilio";

const client = twilio(process.env.TWILIO_SID!, process.env.TWILIO_TOKEN!);

export default function NotifyPage() {
  async function send(formData: FormData) {
    "use server";
    await client.messages.create({
      to: String(formData.get("to")),
      from: process.env.TWILIO_FROM!,
      body: String(formData.get("body")),
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
