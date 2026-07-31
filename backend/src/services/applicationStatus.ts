import { APPLICATION_STATUSES, type ApplicationStatus } from "./db";

export interface ApplicationStatusInfo {
  status: ApplicationStatus;
  label: string;
  description: string;
  whatHappensNext: string;
  /** True once the pipeline has reached a final outcome (no further stage transitions expected). */
  isTerminal: boolean;
}

// Rule-based, not a Claude call — same reasoning as leadScoring.ts: there are
// only 9 fixed statuses, so a templated plain-language explanation is
// cheaper, instant, and perfectly consistent, with zero hallucination risk.
// Retune the copy here, nowhere else.
const STATUS_INFO: Record<ApplicationStatus, Omit<ApplicationStatusInfo, "status">> = {
  not_started: {
    label: "Not Started",
    description:
      "Your profile has been reviewed, but your formal application hasn't been submitted to an institution yet.",
    whatHappensNext:
      "Finish uploading your required documents and confirm your course choice with your counsellor so we can submit your application.",
    isTerminal: false,
  },
  documents_pending: {
    label: "Documents Pending",
    description:
      "We're waiting on one or more required documents (ID/citizenship, academic transcript, IELTS certificate) before your application can be submitted.",
    whatHappensNext: "Check your document checklist and upload whatever is still missing or flagged.",
    isTerminal: false,
  },
  submitted: {
    label: "Submitted",
    description: "Your application has been submitted to the institution and is in their queue.",
    whatHappensNext: "No action needed from you right now — we're waiting for the institution to start reviewing it.",
    isTerminal: false,
  },
  under_review: {
    label: "Under Review",
    description: "The institution is actively reviewing your application and documents.",
    whatHappensNext: "Keep an eye on your email/phone in case the institution or your counsellor needs more information from you.",
    isTerminal: false,
  },
  offer_received: {
    label: "Offer Received",
    description: "Congratulations — the institution has made you an offer.",
    whatHappensNext: "Review the offer conditions with your counsellor, accept it, and begin preparing your visa application.",
    isTerminal: false,
  },
  visa_processing: {
    label: "Visa Processing",
    description: "Your enrollment is confirmed and your student visa application is being processed.",
    whatHappensNext: "Respond promptly to any visa office requests (biometrics, proof of funds, interviews) through your counsellor.",
    isTerminal: false,
  },
  enrolled: {
    label: "Enrolled",
    description: "You're fully enrolled — admission and visa formalities are complete.",
    whatHappensNext: "Prepare for travel and orientation. Congratulations!",
    isTerminal: true,
  },
  rejected: {
    label: "Not Successful",
    description: "This particular application was not successful.",
    whatHappensNext:
      "Talk to your counsellor about alternative courses or institutions — this outcome doesn't affect any other application.",
    isTerminal: true,
  },
  deferred: {
    label: "Deferred",
    description: "Your enrollment has been deferred to a later intake.",
    whatHappensNext:
      "Confirm the new intake date with your counsellor and check whether any documents (e.g. IELTS) will need to be renewed by then.",
    isTerminal: false,
  },
};

export function explainApplicationStatus(status: ApplicationStatus): ApplicationStatusInfo {
  return { status, ...STATUS_INFO[status] };
}

export function listAllApplicationStatuses(): ApplicationStatusInfo[] {
  return APPLICATION_STATUSES.map(explainApplicationStatus);
}
