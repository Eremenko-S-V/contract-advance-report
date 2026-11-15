import unittest
from datetime import date
from decimal import Decimal

from report import (
    Contract,
    Payment,
    Work,
    build_report,
    effective_payment,
    money,
)


def d(s: str):
    return date.fromisoformat(s)


class MoneyTests(unittest.TestCase):
    def test_two_cents(self):
        self.assertEqual(money("100000.00"), Decimal("100000.00"))
        self.assertEqual(money("1,50"), Decimal("1.50"))


class PaymentAsOfTests(unittest.TestCase):
    def test_future_payment_ignored(self):
        p = Payment("P-8", "D-2", None, "Остаток", money("20000"), "paid", d("2026-11-12"), d("2026-11-12"), None)
        self.assertIsNone(effective_payment(p, d("2026-11-10")))

    def test_refunded_net_zero_after_refund(self):
        p = Payment(
            "P-2", "D-1", None, "ошибка", money("50000"), "refunded",
            d("2026-09-02"), d("2026-09-02"), d("2026-09-10"),
        )
        self.assertEqual(effective_payment(p, d("2026-11-10")), ("refunded", Decimal("0.00")))
        self.assertEqual(effective_payment(p, d("2026-09-05")), ("paid", Decimal("50000.00")))

    def test_queued(self):
        p = Payment("P-4", "D-1", None, "Остаток", money("150000"), "queued", d("2026-11-01"), None, None)
        self.assertEqual(effective_payment(p, d("2026-11-10")), ("queued", Decimal("150000.00")))


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.contracts = [
            Contract("D-1", "Студия", money("600000"), d("2026-08-25")),
            Contract("D-2", "Иван", money("90000"), d("2026-09-20")),
        ]
        self.works = [
            Work("W-11", "D-1", "весна", money("100000"), "done", d("2026-09-20"), None),
            Work("W-12", "D-1", "лето", money("100000"), "done", d("2026-10-05"), None),
            Work("W-13", "D-1", "аксессуары", money("100000"), "cancelled", None, d("2026-10-12")),
            Work("W-14", "D-1", "осень", money("100000"), "done", d("2026-10-28"), None),
            Work("W-15", "D-1", "зима", money("100000"), "planned", None, None),
            Work("W-16", "D-1", "нг", money("100000"), "planned", None, None),
            Work("W-21", "D-2", "логотип", money("20000"), "done", d("2026-10-01"), None),
            Work("W-22", "D-2", "стиль", money("30000"), "done", d("2026-10-10"), None),
            Work("W-23", "D-2", "упаковка", money("40000"), "done", d("2026-11-11"), None),
        ]
        self.payments = [
            Payment("P-1", "D-1", None, "Аванс 50%", money("300000"), "paid", d("2026-08-30"), d("2026-09-01"), None),
            Payment("P-2", "D-1", None, "ошибка", money("50000"), "refunded", d("2026-09-02"), d("2026-09-02"), d("2026-09-10")),
            Payment("P-3", "D-1", "W-14", "материалы", money("15000"), "paid", d("2026-10-24"), d("2026-10-25"), None),
            Payment("P-4", "D-1", None, "Остаток", money("150000"), "queued", d("2026-11-01"), None, None),
            Payment("P-5", "D-2", None, "Аванс 50%", money("45000"), "paid", d("2026-09-24"), d("2026-09-25"), None),
            Payment("P-6", "D-2", None, "Остаток", money("25000"), "paid", d("2026-10-29"), d("2026-10-30"), None),
            Payment("P-7", "D-2", None, "Доплата", money("5000"), "paid", d("2026-11-02"), d("2026-11-02"), None),
            Payment("P-8", "D-2", None, "Остаток", money("20000"), "paid", d("2026-11-12"), d("2026-11-12"), None),
        ]

    def test_as_of_10_nov(self):
        reports = {r.contract.contract_id: r for r in build_report(self.contracts, self.works, self.payments, d("2026-11-10"))}
        d1 = reports["D-1"]
        by_id = {line.work.work_id: line for line in d1.works}
        self.assertEqual(by_id["W-13"].status, "cancelled")
        self.assertEqual(by_id["W-13"].remaining, Decimal("0.00"))
        self.assertEqual(by_id["W-11"].paid, Decimal("100000.00"))
        self.assertEqual(by_id["W-12"].paid, Decimal("100000.00"))
        self.assertEqual(by_id["W-14"].paid, Decimal("100000.00"))
        self.assertEqual(by_id["W-14"].direct_paid, Decimal("15000.00"))
        self.assertEqual(by_id["W-15"].paid, Decimal("15000.00"))
        self.assertEqual(by_id["W-16"].paid, Decimal("0.00"))
        self.assertEqual(d1.paid, Decimal("315000.00"))
        self.assertEqual(d1.queued, Decimal("150000.00"))
        self.assertEqual(d1.obligation, Decimal("500000.00"))
        self.assertEqual(d1.remaining, Decimal("185000.00"))

        d2 = reports["D-2"]
        by_id = {line.work.work_id: line for line in d2.works}
        self.assertEqual(by_id["W-23"].status, "planned")
        self.assertEqual(by_id["W-21"].paid, Decimal("20000.00"))
        self.assertEqual(by_id["W-22"].paid, Decimal("30000.00"))
        self.assertEqual(by_id["W-23"].paid, Decimal("25000.00"))
        self.assertEqual(d2.paid, Decimal("75000.00"))
        self.assertEqual(d2.remaining, Decimal("15000.00"))

    def test_after_p8_overpay(self):
        reports = {r.contract.contract_id: r for r in build_report(self.contracts, self.works, self.payments, d("2026-11-12"))}
        d2 = reports["D-2"]
        by_id = {line.work.work_id: line for line in d2.works}
        self.assertEqual(by_id["W-23"].status, "done")
        self.assertEqual(d2.paid, Decimal("95000.00"))
        self.assertEqual(d2.remaining, Decimal("0.00"))
        self.assertEqual(d2.overpaid, Decimal("5000.00"))


if __name__ == "__main__":
    unittest.main()
