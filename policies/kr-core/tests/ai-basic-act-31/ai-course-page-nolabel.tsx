import Link from "next/link";

const curriculum = ["모델 개론", "프롬프트 설계", "업무 자동화 사례", "윤리와 법"];

export default function AiCoursePage() {
  return (
    <main>
      <h1>직장인을 위한 실무 과정</h1>
      <p>ChatGPT를 업무에 쓰는 법을 8주 동안 배웁니다.</p>
      <ol>
        {curriculum.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ol>
      <Link href="/courses/ai/apply">수강 신청</Link>
    </main>
  );
}
