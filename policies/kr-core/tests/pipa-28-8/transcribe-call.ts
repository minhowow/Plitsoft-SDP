import fs from "node:fs";
import OpenAI from "openai";

const openai = new OpenAI();

export async function transcribeCall(call: { customerName: string; recordingPath: string }) {
  const out = await openai.audio.transcriptions.create({ model: "whisper-1", file: fs.createReadStream(call.recordingPath) });
  return { customer: call.customerName, text: out.text };
}
