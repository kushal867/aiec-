import { pipeline, type FeatureExtractionPipeline, type Tensor } from "@huggingface/transformers";
import { config } from "../config";

type InputType = "query" | "document";

// BGE models are trained asymmetrically: queries get this instruction prefix,
// documents/passages do not. Improves retrieval quality over embedding both
// sides identically. https://huggingface.co/BAAI/bge-small-en-v1.5
const QUERY_PREFIX = "Represent this sentence for searching relevant passages: ";

let extractorPromise: Promise<FeatureExtractionPipeline> | null = null;

function getExtractor(): Promise<FeatureExtractionPipeline> {
  if (!extractorPromise) {
    // Runs fully locally (ONNX, CPU) — no API key, no network calls at
    // inference time, no per-request cost. Model weights download once from
    // the Hugging Face Hub on first run and are cached under ~/.cache.
    extractorPromise = pipeline("feature-extraction", config.embeddingModel);
  }
  return extractorPromise;
}

export async function embedTexts(texts: string[], inputType: InputType): Promise<number[][]> {
  const extractor = await getExtractor();
  const inputs = inputType === "query" ? texts.map((t) => QUERY_PREFIX + t) : texts;
  const output = (await extractor(inputs, { pooling: "mean", normalize: true })) as Tensor;
  return output.tolist() as number[][];
}

export async function embedQuery(text: string): Promise<number[]> {
  const [embedding] = await embedTexts([text], "query");
  return embedding;
}
