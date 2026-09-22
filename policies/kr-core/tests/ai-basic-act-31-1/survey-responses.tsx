import { createClient } from "@/lib/typeform";

const tf = createClient({ token: process.env.TF_TOKEN! });

export default async function FeedbackPage() {
  async function submit(fd: FormData) {
    "use server";
    await tf.responses.create({ formId: "abc", answers: Object.fromEntries(fd) });
  }

  return (
    <form action={submit}>
      <label>
        서비스에 만족하셨나요?
        <input name="q1" />
      </label>
      <button>제출</button>
    </form>
  );
}
