import { cookies } from "next/headers";
import sharp from "sharp";
import { openai } from "@/lib/openai";
import { DismissibleNotice } from "@/components/DismissibleNotice";

const IPTC_TRAINED = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia";

function xmpFor(tool: string) {
  return (
    '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">' +
    `<rdf:Description xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/" Iptc4xmpExt:DigitalSourceType="${IPTC_TRAINED}"` +
    ` xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:CreatorTool="${tool}"/></rdf:RDF></x:xmpmeta>`
  );
}

async function drawPoster(prompt: string) {
  const res = await openai.images.generate({ model: "gpt-image-1", prompt, size: "1024x1024" });
  const png = await sharp(Buffer.from(res.data![0].b64_json!, "base64"))
    .withXmp(xmpFor("gpt-image-1"))
    .png()
    .toBuffer();
  return `data:image/png;base64,${png.toString("base64")}`;
}

export default async function PosterPage({ searchParams }: { searchParams: { q?: string } }) {
  const noticeSeen = cookies().get("poster_notice_seen");
  const src = searchParams.q ? await drawPoster(searchParams.q) : null;
  return (
    <main className="poster">
      {!noticeSeen && (
        <DismissibleNotice cookie="poster_notice_seen">
          이 페이지의 포스터 이미지는 인공지능 모델이 그리며, 이미지 파일의 메타데이터에 그 사실이 기록됩니다.
        </DismissibleNotice>
      )}
      {src && <img src={src} alt="" width={512} height={512} />}
    </main>
  );
}
