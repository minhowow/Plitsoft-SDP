import type { Metadata } from "next";
import { experimental_generateImage as generateImage } from "ai";
import { openai } from "@ai-sdk/openai";

export const metadata: Metadata = { title: "AI 이미지 생성기" };

export default function ImageMakerPage() {
  async function make(formData: FormData) {
    "use server";
    const { image } = await generateImage({
      model: openai.image("dall-e-3"),
      prompt: String(formData.get("prompt")),
    });
    return image.base64;
  }

  return (
    <section>
      <h1>AI 이미지 생성기</h1>
      <p>문장을 입력하면 AI가 이미지를 그려 드립니다.</p>
      <form action={make}>
        <input name="prompt" />
        <button>그리기</button>
      </form>
    </section>
  );
}
