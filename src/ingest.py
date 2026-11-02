"""Fetch the Cookie Cats A/B test dataset into data/raw/cookie_cats.csv.

Public Kaggle dataset (mobile game "Cookie Cats": players randomized to
the first progression gate at level 30 vs. level 40). kagglehub is tried
first; if it is unavailable, download the CSV manually from Kaggle
(search "Cookie Cats A/B testing") and save it as data/raw/cookie_cats.csv.
"""

import shutil
import sys
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
TARGET = RAW_DIR / "cookie_cats.csv"
DATASET = "yufengsui/mobile-games-ab-testing"
EXPECTED_COLUMNS = {"userid", "version", "sum_gamerounds", "retention_1", "retention_7"}


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if not TARGET.exists():
        try:
            import kagglehub

            cache = Path(kagglehub.dataset_download(DATASET))
            csv = next(cache.glob("*.csv"))
            shutil.copy2(csv, TARGET)
        except Exception as exc:  # noqa: BLE001 - surface any download problem as one actionable message
            sys.exit(f"Automatic download failed ({exc}).\nDownload the Cookie Cats CSV from Kaggle and save it as {TARGET}")

    header = set(TARGET.read_text(encoding="utf-8").splitlines()[0].split(","))
    missing = EXPECTED_COLUMNS - header
    if missing:
        sys.exit(f"{TARGET.name} is missing expected columns: {sorted(missing)}")
    print(f"Ready: {TARGET}")


if __name__ == "__main__":
    main()
