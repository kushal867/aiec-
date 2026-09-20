"""
Loads the base model + fine-tuned LoRA adapter and runs a few sanity-check
questions to verify the fine-tune actually produces grounded, sensible
answers before wiring it into the live chat route. Fully offline/local
inference — no Claude, no external API.

Usage:
    python -m app.scripts.test_finetuned_model
"""

from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

BASE_MODEL = "Qwen/Qwen2.5-3B-Instruct"
ADAPTER_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "finetuned" / "aiec-chat-lora"

SYSTEM_PROMPT = (
    "You are the AIEC Global study-abroad counsellor assistant. You answer student "
    "questions about courses, universities, fees, IELTS requirements, and countries "
    "using only the real data you are given. Never invent a course, university, fee, "
    "or policy detail that isn't in your data. If you don't know something, say so "
    "honestly and suggest a human counsellor. Reply in the same language style "
    "(English or Romanized Nepali) as the student's question."
)

TEST_QUESTIONS = [
    "What courses are available in Canada?",
    "How long does the visa process take for Australia?",
    "What is a No Objection Certificate?",
    "Do you have nursing courses in the UK?",
    "hi",
]


def main() -> None:
    print(f"Loading base model {BASE_MODEL} in 4-bit...")
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, quantization_config=bnb_config, device_map="auto")

    print(f"Applying LoRA adapter from {ADAPTER_DIR}...")
    model = PeftModel.from_pretrained(model, str(ADAPTER_DIR))
    model.eval()

    for question in TEST_QUESTIONS:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

        with torch.no_grad():
            output = model.generate(
                **inputs,
                max_new_tokens=300,
                do_sample=False,
                temperature=None,
                top_p=None,
                pad_token_id=tokenizer.eos_token_id,
            )

        reply = tokenizer.decode(output[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        print("=" * 70)
        print("Q:", question)
        print("A:", reply.strip())
        print()


if __name__ == "__main__":
    main()
