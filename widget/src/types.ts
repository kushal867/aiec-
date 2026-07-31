export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface SourceRef {
  document: string;
  page: number;
}

export interface CourseRef {
  courseName: string;
  university: string | null;
  country: string;
  feePerYear: number | null;
}

export interface ChatApiRequest {
  messages: ChatMessage[];
  sessionId?: string;
}

export interface ChatApiResponse {
  reply: string;
  sources: SourceRef[];
  coursesReferenced: CourseRef[];
  sessionId?: string;
}

export const PREFERRED_COUNTRY_ANY = "ANY";

export type AcademicBackground = "high_school" | "bachelors" | "masters" | "phd";

export const ACADEMIC_BACKGROUND_OPTIONS: { value: AcademicBackground; label: string }[] = [
  { value: "high_school", label: "High School" },
  { value: "bachelors", label: "Bachelor's Degree" },
  { value: "masters", label: "Master's Degree" },
  { value: "phd", label: "PhD" },
];

export type MigrationIntent = "study_only" | "study_then_work" | "migrate_permanently" | "undecided";

export const MIGRATION_INTENT_OPTIONS: { value: MigrationIntent; label: string }[] = [
  { value: "study_only", label: "Study only, then return home" },
  { value: "study_then_work", label: "Study, then work abroad for a while" },
  { value: "migrate_permanently", label: "Migrate / settle permanently" },
  { value: "undecided", label: "Not sure yet" },
];

export interface ProfileFormValues {
  fullName: string;
  email: string;
  phone: string;
  gpa: number;
  ielts: number;
  budget: number;
  gap: number;
  academicBackground: AcademicBackground;
  careerGoals: string;
  migrationIntent: MigrationIntent;
  preferredCountry: string;
}

export type LeadStatus = "Hot" | "Warm" | "Cold";

export interface SuggestedCounsellor {
  id: number;
  name: string;
}

export interface ProfileAnalyzeResponse {
  reply: string;
  status: LeadStatus;
  score: number;
  recommendedCountries: string[];
  nextSteps: string[];
  suggestedCounsellor: SuggestedCounsellor | null;
  referenceCode: string;
  sessionId: string;
}

export type DocumentType = "citizenship" | "marksheet" | "ielts_certificate";

export type DocumentVerificationStatus = "valid" | "issues_found" | "unclear";

export interface DocumentChecklistItem {
  documentType: DocumentType;
  label: string;
  uploaded: boolean;
  status: DocumentVerificationStatus | null;
  issues: string[];
  uploadedAt: string | null;
}

export interface DocumentChecklist {
  items: DocumentChecklistItem[];
  missing: DocumentType[];
  needsAttention: DocumentType[];
  complete: boolean;
}

export interface DocumentVerificationResponse {
  documentType: DocumentType;
  status: DocumentVerificationStatus;
  issues: string[];
  extractedSummary: string;
  message: string;
  sessionId: string;
  checklist: DocumentChecklist;
}

export interface DocumentChecklistResponse {
  sessionId: string;
  checklist: DocumentChecklist;
}

export type ApplicationStatus =
  | "not_started"
  | "documents_pending"
  | "submitted"
  | "under_review"
  | "offer_received"
  | "visa_processing"
  | "enrolled"
  | "rejected"
  | "deferred";

export interface ApplicationStatusInfo {
  status: ApplicationStatus;
  label: string;
  description: string;
  whatHappensNext: string;
  isTerminal: boolean;
}

export interface StatusLookupResponse {
  referenceCode: string;
  name: string;
  applicationStatus: ApplicationStatusInfo;
  documentChecklist: DocumentChecklist;
  updatedAt: string;
}

export interface StudyPathStage {
  title: string;
  description: string;
  estimatedTimeframe: string;
}

export interface StudyPathResponse {
  stages: StudyPathStage[];
  sessionId: string;
}
