export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatRequest {
  messages: ChatMessage[];
  sessionId?: string;
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

export interface ChatResponse {
  reply: string;
  sources: SourceRef[];
  coursesReferenced: CourseRef[];
  sessionId?: string;
}

export interface Chunk {
  id: number;
  text: string;
  document: string;
  page: number;
  chunkIndex: number;
}

export interface RetrievedChunk extends Chunk {
  similarity: number;
}
