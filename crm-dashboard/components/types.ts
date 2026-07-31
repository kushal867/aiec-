export type LeadStatus = "Hot" | "Warm" | "Cold";

export type UserRole = "admin" | "counsellor";

export interface AuthUser {
  id: number;
  name: string;
  email: string;
  role: UserRole;
}

export interface Counsellor {
  id: number;
  name: string;
  email: string;
}

export type DocumentType = "citizenship" | "marksheet" | "ielts_certificate";
export type DocumentVerificationStatus = "valid" | "issues_found" | "unclear";

export interface DocumentRecord {
  documentType: DocumentType;
  filename: string;
  status: DocumentVerificationStatus;
  issues: string[];
  extractedSummary: string;
  uploadedAt: string;
}

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

export const APPLICATION_STATUSES: ApplicationStatus[] = [
  "not_started",
  "documents_pending",
  "submitted",
  "under_review",
  "offer_received",
  "visa_processing",
  "enrolled",
  "rejected",
  "deferred",
];

export interface ApplicationStatusInfo {
  status: ApplicationStatus;
  label: string;
  description: string;
  whatHappensNext: string;
  isTerminal: boolean;
}

export interface InactivityInfo {
  isInactive: boolean;
  daysSinceContact: number | null;
  thresholdDays: number;
}

export type ConversionLikelihood = "Very Likely" | "Likely" | "Possible" | "Unlikely";

export interface ConversionPrediction {
  probability: number;
  likelihood: ConversionLikelihood;
  factors: string[];
}

export interface StudyPathStage {
  title: string;
  description: string;
  estimatedTimeframe: string;
}

export interface Lead {
  id: number;
  sessionId: string;
  referenceCode: string | null;
  name: string;
  email: string | null;
  phone: string | null;
  gpa: number;
  ielts: number;
  budget: number;
  gap: number;
  academicBackground: string | null;
  careerGoals: string | null;
  migrationIntent: string | null;
  preferredCountry: string | null;
  score: number;
  status: LeadStatus;
  countries: string | null;
  aiResponse: string | null;
  nextSteps: string[];
  documents: DocumentRecord[];
  documentChecklist: DocumentChecklist;
  counsellorNotes: string | null;
  applicationStatus: ApplicationStatusInfo;
  applicationStatusUpdatedAt: string | null;
  assignedCounsellorId: number | null;
  suggestedCounsellorId: number | null;
  lastContactedAt: string | null;
  followupSuggestion: string | null;
  followupAction: string | null;
  followupTiming: string | null;
  followupGeneratedAt: string | null;
  inactivity: InactivityInfo;
  conversionPrediction: ConversionPrediction;
  studyPath: StudyPathStage[] | null;
  studyPathGeneratedAt: string | null;
  createdAt: string;
  updatedAt: string;
}
