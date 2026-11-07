const { GoogleGenerativeAI } = require("@google/generative-ai");

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);
const model = genAI.getGenerativeModel({ model: "gemini-2.0-flash" });

async function explainResult(patientRecord) {
  const prompt = `환자 ${patientRecord.patientName}의 검사 결과를 쉬운 말로 설명해 주세요: ${patientRecord.diagnosis}`;
  const result = await model.generateContent(prompt);
  return result.response.text();
}

module.exports = { explainResult };
