from app.config import config
from app.db import get_db
from app.services.conversion_model import train_and_save


def main() -> None:
    conn = get_db()
    row_count = train_and_save(conn)

    if row_count < config.conversion_model_min_training_rows:
        print(
            f"Only {row_count} terminal-outcome lead(s) on file "
            f"(need {config.conversion_model_min_training_rows}) — "
            "still using the rule-based fallback in conversion_prediction.py."
        )
        return

    print(f"Trained conversion model on {row_count} real lead outcomes.")
    print(f"Saved to {config.conversion_model_path}")


if __name__ == "__main__":
    main()
