import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from observability.ledger_hygiene import backfill_revenue_classification
from observability.economic_ledger import ledger

if __name__ == "__main__":
    updated = backfill_revenue_classification()
    print("updated:", updated)
    print("net:", ledger.calculate_net())