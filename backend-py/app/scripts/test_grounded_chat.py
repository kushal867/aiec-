"""
Sanity-checks the RAG-grounded local chat pipeline (real retrieval + the
fine-tuned model only phrasing from that retrieved data) on the same
questions that exposed hallucination in the ungrounded test.

Usage:
    python -m app.scripts.test_grounded_chat
"""

from app.services.local_chat_generation import generate_grounded_answer

TEST_QUESTIONS = [
    "What courses are available in Canada?",
    "How long does the visa process take for Australia?",
    "What is a No Objection Certificate?",
    "Do you have nursing courses in the UK?",
    "What is PTE?",
    "Can my family come with me on a student visa?",
    "Which universities are in Canada?",
    "What are the top universities in Australia?",
    "hi",
]


def main() -> None:
    for question in TEST_QUESTIONS:
        answer = generate_grounded_answer(question)
        print("=" * 70)
        print("Q:", question)
        print("A:", answer.reply)
        if answer.sources:
            print("Sources:", answer.sources)
        print()


if __name__ == "__main__":
    main()
