import unittest
from datetime import datetime, date, timedelta
from pathlib import Path

import pandas as pd
import pytz

from workflows import payments


class TestPayments(unittest.TestCase):

    def setUp(self):
        # sample rates CSV
        self.rates_csv = Path("tests/data/rates_test.csv")
        self.schema_csv = Path("tests/data/schema_test.csv")

        # create sample sessions DataFrame
        now_utc = datetime(2025, 5, 1, 12, tzinfo=pytz.UTC)
        self.sessions = pd.DataFrame([
            {
                "session_id": f"s{i}",
                "within_study_id": "p1",
                "survey_name": "Completed an EMA survey",
                "started_at_utc": now_utc + timedelta(days=i)
            }
            for i in range(5)
        ])

    def test_load_rates(self):
        # create a temporary CSV file
        df = pd.DataFrame({
            "id": ["1", "2"],
            "rate": ["$10.00", "$5.50"],
            "reason": ["Test A", "Test B"]
        })
        df.to_csv(self.rates_csv, index=False)
        loaded = payments.load_rates(self.rates_csv)
        self.assertEqual(list(loaded.columns), ["id", "reason", "rate_amount"])
        self.assertAlmostEqual(loaded["rate_amount"].sum(), 15.5)

    def test_load_schema(self):
        df = pd.DataFrame({
            "name": ["S1"],
            "rate_id": ["1"],
            "num_possible_per_day": ["2"],
            "num_days": ["3"],
            "bonus_rate_id": [""],
            "bonus_threshold": [""]
        })
        df.to_csv(self.schema_csv, index=False)
        loaded = payments.load_schema(self.schema_csv)
        self.assertEqual(loaded.loc[0, "num_days"], 3)
        self.assertEqual(loaded.loc[0, "bonus_threshold"], 0)

    def test_get_valid_participants(self):
        vp = payments.get_valid_participants(self.sessions)
        self.assertEqual(vp, ["p1"])

    def test_filter_sessions_by_participant(self):
        tz = pytz.timezone("UTC")
        filt = payments.filter_sessions_by_participant(
            self.sessions, "p1", tz
        )
        self.assertIn("local_ts", filt.columns)
        self.assertEqual(len(filt), 5)

    def test_has_sessions_after_end(self):
        tz = pytz.UTC
        # start_date such that only 2 days fit in window of 2 days
        filt = payments.filter_sessions_by_participant(
            self.sessions, "p1", tz
        )
        # with days=2, there should be sessions after end (day 3,4)
        self.assertTrue(payments.has_sessions_after_end(
            filt, date(2025, 5, 1), days=2, tz=tz
        ))

    def test_get_rate_reason(self):
        rates = pd.DataFrame({
            "id": ["x"], "reason": ["Foo"]
        })
        self.assertEqual(payments.get_rate_reason(rates, "x"), "Foo")
        self.assertEqual(payments.get_rate_reason(rates, "y"), "")

    def test_compute_daily_counts(self):
        tz = pytz.timezone("America/New_York")
        filt = payments.filter_sessions_by_participant(
            self.sessions, "p1", tz
        )
        daily = payments.compute_daily_counts(
            filt, start_date=date(2025, 5, 2),
            days=4, tz=tz,
            reason_filter="ema survey"
        )
        # fake a 4-day schema; days 1–4 have one each
        self.assertEqual(len(daily), 4)
        # each count should be either 1 or 0
        self.assertTrue((daily["count"] >= 0).all())

    def test_compute_bonus_days(self):
        df = pd.DataFrame({"count": [0, 1, 5, 2]})
        self.assertEqual(payments.compute_bonus_days(df, threshold=2), 2)
        self.assertEqual(payments.compute_bonus_days(df, threshold=0), 0)

    def test_compute_base_rate_counts_and_total(self):
        tz = pytz.UTC
        filt = payments.filter_sessions_by_participant(
            self.sessions, "p1", tz
        )
        rates = pd.DataFrame({
            "id": ["1"],
            "reason": ["ema survey"],
            "rate_amount": [2.0]
        })
        table = payments.compute_base_rate_counts(filt, rates)
        self.assertEqual(table.loc[0, "count"], 5)
        # TODO: assert that the total displayed is correct

class TestComputeStats(unittest.TestCase):
    def setUp(self):
        # common schema and daily‐counts
        # schema: 10 days total, 1 possible survey per day
        self.schema = {
            "num_days": 10,
            "num_possible_per_day": 1,
            "bonus_threshold": 0  # unused here
        }
        # pretend they completed 3 surveys total
        self.daily = pd.DataFrame({"count": [1, 0, 2]})
        self.tz = pytz.UTC

        # save original datetime and restore in tearDown
        self._orig_datetime = payments.datetime

    def tearDown(self):
        payments.datetime = self._orig_datetime

    def test_before_schema_start_returns_zero(self):
        start = date(2025, 5, 10)

        # patch today → May 9, 2025 (one day before start)
        class FixedNow:
            @classmethod
            def now(cls, tz):
                return datetime(2025, 5, 9, 12, tzinfo=tz)

        payments.datetime = FixedNow

        possible, completed = payments.compute_stats(
            start_date=start,
            tz=self.tz,
            schema_row=self.schema,
            daily=self.daily
        )
        self.assertEqual(possible, 0)
        self.assertEqual(completed, 0)

    def test_mid_schema_counts_half_possible(self):
        start = date(2025, 5, 1)

        # patch today → May 6, 2025 (5 days after start)
        class FixedNow:
            @classmethod
            def now(cls, tz):
                return datetime(2025, 5, 6, 9, tzinfo=tz)

        payments.datetime = FixedNow

        # days_completed = min(10, (6–1)=5 + 1) → 6 # add 1 for today
        # num_possible = 6 * 1 = 6
        # num_completed = sum(self.daily.count) = 3
        possible, completed = payments.compute_stats(
            start_date=start,
            tz=self.tz,
            schema_row=self.schema,
            daily=self.daily
        )
        self.assertEqual(possible, 6)
        self.assertEqual(completed, 3)

    def test_after_schema_end_counts_full(self):
        start = date(2025, 4, 1)

        # patch today → May 20, 2025 (well after 10‐day window)
        class FixedNow:
            @classmethod
            def now(cls, tz):
                return datetime(2025, 5, 20, 0, tzinfo=tz)

        payments.datetime = FixedNow

        # days_completed = min(10, (20–1)=49) → 10
        # num_possible = 10 * 1 = 10
        # num_completed = 3
        possible, completed = payments.compute_stats(
            start_date=start,
            tz=self.tz,
            schema_row=self.schema,
            daily=self.daily
        )
        self.assertEqual(possible, 10)
        self.assertEqual(completed, 3)


if __name__ == "__main__":
    unittest.main()
