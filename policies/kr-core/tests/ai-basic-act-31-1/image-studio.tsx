import OpenAI from "openai";
import { revalidatePath } from "next/cache";
import { saveImage, listImages } from "@/lib/images";

const openai = new OpenAI();

export default async function StudioPage() {
  const images = await listImages();

  async function create(formData: FormData) {
    "use server";
    const res = await openai.images.generate({
      model: "gpt-image-1",
      prompt: String(formData.get("prompt")),
      size: "1024x1024",
    });
    await saveImage(res.data[0].b64_json!);
    revalidatePath("/studio");
  }

  return (
    <section>
      <h1>썸네일 스튜디오</h1>
      <form action={create}>
        <textarea name="prompt" placeholder="원하는 썸네일을 설명하세요" />
        <button type="submit">만들기</button>
      </form>
      <div className="grid grid-cols-3 gap-2">
        {images.map((src) => <img key={src} src={src} alt="" />)}
      </div>
    </section>
  );
}
