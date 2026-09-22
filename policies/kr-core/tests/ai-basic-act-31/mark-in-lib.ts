import sharp from "sharp";

export async function finalizeImage(b64: string, model = "gpt-image-1") {
  return sharp(Buffer.from(b64, "base64"))
    .withExif({ IFD0: { ImageDescription: "trainedAlgorithmicMedia", Software: model } })
    .png()
    .toBuffer();
}
