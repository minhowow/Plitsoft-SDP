import fs from "node:fs";
import OpenAI from "openai";

const openai = new OpenAI();

export async function translateMemo(patientId: string, path: string) {
  const out = await openai.audio.translations.create({ model: "whisper-1", file: fs.createReadStream(path) });
  return { patientId, text: out.text };
}
