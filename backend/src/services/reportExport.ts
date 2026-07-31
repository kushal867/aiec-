import PDFDocument from "pdfkit";
import { Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType } from "docx";
import type { StudentRow } from "./db";
import { explainApplicationStatus } from "./applicationStatus";
import {
  PREFERRED_COUNTRY_ANY,
  ACADEMIC_BACKGROUND_LABELS,
  MIGRATION_INTENT_LABELS,
  type AcademicBackground,
  type MigrationIntent,
} from "./leadScoring";

interface ReportData {
  name: string;
  email: string | null;
  phone: string | null;
  referenceCode: string | null;
  generatedAt: string;
  profile: { label: string; value: string }[];
  recommendedCountries: string;
  aiResponse: string;
  nextSteps: string[];
  applicationStatus: { label: string; description: string };
}

// Deliberately excludes internal CRM-only fields (Hot/Warm/Cold score,
// counsellor notes, assignment, follow-up data) — this document is the
// student's own copy of their recommendation, not a CRM record.
function buildReportData(row: StudentRow): ReportData {
  const statusInfo = explainApplicationStatus(row.application_status);
  return {
    name: row.name,
    email: row.email,
    phone: row.phone,
    referenceCode: row.reference_code,
    generatedAt: new Date().toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" }),
    profile: [
      { label: "GPA", value: `${row.gpa} / 4.0` },
      { label: "IELTS", value: `${row.ielts} / 9.0` },
      { label: "Annual Budget", value: `$${row.budget.toLocaleString()} USD` },
      { label: "Study Gap", value: `${row.gap} year(s)` },
      {
        label: "Academic Background",
        value: row.academic_background
          ? (ACADEMIC_BACKGROUND_LABELS[row.academic_background as AcademicBackground] ?? row.academic_background)
          : "—",
      },
      { label: "Career Goals", value: row.career_goals || "—" },
      {
        label: "Migration Intent",
        value: row.migration_intent
          ? (MIGRATION_INTENT_LABELS[row.migration_intent as MigrationIntent] ?? row.migration_intent)
          : "—",
      },
      {
        label: "Preferred Country",
        value:
          row.preferred_country && row.preferred_country !== PREFERRED_COUNTRY_ANY
            ? row.preferred_country
            : "Any / Let AI decide",
      },
    ],
    recommendedCountries: row.countries || "—",
    aiResponse: row.ai_response || "(No recommendation on file yet.)",
    nextSteps: row.next_steps ? (JSON.parse(row.next_steps) as string[]) : [],
    applicationStatus: { label: statusInfo.label, description: statusInfo.description },
  };
}

export function generateReportPdf(row: StudentRow): Promise<Buffer> {
  const data = buildReportData(row);

  return new Promise((resolve, reject) => {
    const doc = new PDFDocument({ margin: 50 });
    const chunks: Buffer[] = [];
    doc.on("data", (chunk) => chunks.push(chunk));
    doc.on("end", () => resolve(Buffer.concat(chunks)));
    doc.on("error", reject);

    doc.fontSize(20).font("Helvetica-Bold").fillColor("#1a5f7a").text("AIEC Global");
    doc.fontSize(13).font("Helvetica").fillColor("#555").text("Study Abroad Recommendation Report");
    doc.moveDown(0.3);
    doc
      .fontSize(9)
      .fillColor("#999")
      .text(`Generated ${data.generatedAt}${data.referenceCode ? `  ·  Reference: ${data.referenceCode}` : ""}`);
    doc.moveDown(1);
    doc.fillColor("#000");

    doc.fontSize(14).font("Helvetica-Bold").text(data.name);
    const contactLine = [data.email, data.phone].filter(Boolean).join("  ·  ");
    if (contactLine) doc.fontSize(10).font("Helvetica").fillColor("#555").text(contactLine);
    doc.fillColor("#000");
    doc.moveDown(1);

    sectionHeading(doc, "Your Profile");
    data.profile.forEach(({ label, value }) => {
      doc.fontSize(10).font("Helvetica-Bold").text(`${label}: `, { continued: true }).font("Helvetica").text(value);
    });
    doc.moveDown(1);

    sectionHeading(doc, "Recommended Countries");
    doc.fontSize(10).font("Helvetica").text(data.recommendedCountries);
    doc.moveDown(1);

    sectionHeading(doc, "AI Recommendation");
    doc.fontSize(10).font("Helvetica").text(data.aiResponse, { align: "left" });
    doc.moveDown(1);

    if (data.nextSteps.length > 0) {
      sectionHeading(doc, "Next Steps");
      data.nextSteps.forEach((step, i) => {
        doc.fontSize(10).font("Helvetica").text(`${i + 1}. ${step}`);
      });
      doc.moveDown(1);
    }

    sectionHeading(doc, "Current Application Status");
    doc
      .fontSize(10)
      .font("Helvetica-Bold")
      .text(data.applicationStatus.label, { continued: true })
      .font("Helvetica")
      .text(` — ${data.applicationStatus.description}`);

    doc.moveDown(2);
    doc.fontSize(8).fillColor("#999").text("Questions about this report? Contact your AIEC Global counsellor.");

    doc.end();
  });
}

function sectionHeading(doc: PDFKit.PDFDocument, text: string): void {
  doc.fontSize(12).font("Helvetica-Bold").fillColor("#1a5f7a").text(text);
  doc.fillColor("#000");
  doc.moveDown(0.3);
}

export async function generateReportDocx(row: StudentRow): Promise<Buffer> {
  const data = buildReportData(row);

  const heading = (text: string) =>
    new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 240, after: 120 }, children: [new TextRun({ text, color: "1a5f7a" })] });

  const doc = new Document({
    sections: [
      {
        children: [
          new Paragraph({
            children: [new TextRun({ text: "AIEC Global", bold: true, size: 40, color: "1a5f7a" })],
          }),
          new Paragraph({
            children: [new TextRun({ text: "Study Abroad Recommendation Report", size: 26, color: "555555" })],
            spacing: { after: 80 },
          }),
          new Paragraph({
            children: [
              new TextRun({
                text: `Generated ${data.generatedAt}${data.referenceCode ? `  ·  Reference: ${data.referenceCode}` : ""}`,
                size: 18,
                color: "999999",
              }),
            ],
            spacing: { after: 200 },
          }),
          new Paragraph({ children: [new TextRun({ text: data.name, bold: true, size: 28 })] }),
          ...(data.email || data.phone
            ? [
                new Paragraph({
                  children: [
                    new TextRun({ text: [data.email, data.phone].filter(Boolean).join("  ·  "), size: 20, color: "555555" }),
                  ],
                  spacing: { after: 200 },
                }),
              ]
            : []),

          heading("Your Profile"),
          ...data.profile.map(
            ({ label, value }) =>
              new Paragraph({
                children: [new TextRun({ text: `${label}: `, bold: true }), new TextRun({ text: value })],
              }),
          ),

          heading("Recommended Countries"),
          new Paragraph({ text: data.recommendedCountries }),

          heading("AI Recommendation"),
          ...data.aiResponse.split("\n").map((line) => new Paragraph({ text: line })),

          ...(data.nextSteps.length > 0
            ? [heading("Next Steps"), ...data.nextSteps.map((step, i) => new Paragraph({ text: `${i + 1}. ${step}` }))]
            : []),

          heading("Current Application Status"),
          new Paragraph({
            children: [
              new TextRun({ text: data.applicationStatus.label, bold: true }),
              new TextRun({ text: ` — ${data.applicationStatus.description}` }),
            ],
          }),

          new Paragraph({
            spacing: { before: 400 },
            alignment: AlignmentType.LEFT,
            children: [
              new TextRun({ text: "Questions about this report? Contact your AIEC Global counsellor.", size: 16, color: "999999" }),
            ],
          }),
        ],
      },
    ],
  });

  return Packer.toBuffer(doc);
}
