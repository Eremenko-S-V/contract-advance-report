#!/usr/bin/env python3
"""Отчёт: сколько выплачено и сколько осталось по работам и договорам.

Запуск:
    python report.py
    python report.py --date 2026-11-10
    python report.py --date 2026-11-10 --data data --csv report.csv

Без сторонних библиотек. Суммы считаются в decimal.Decimal, без float.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Optional

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
DEFAULT_DATE = date(2026, 11, 10)


def money(value: object) -> Decimal:
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        quantized = value
    else:
        quantized = Decimal(str(value).strip().replace(" ", "").replace(",", "."))
    return quantized.quantize(CENT, rounding=ROUND_HALF_UP)


def parse_date(value: str) -> Optional[date]:
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def fmt(amount: Decimal) -> str:
    return f"{money(amount):.2f}"


@dataclass
class Contract:
    contract_id: str
    contractor: str
    amount: Decimal
    signed_at: date


@dataclass
class Work:
    work_id: str
    contract_id: str
    title: str
    price: Decimal
    status: str
    completed_at: Optional[date]
    cancelled_at: Optional[date]

    def status_as_of(self, as_of: date) -> str:
        if self.cancelled_at and self.cancelled_at <= as_of:
            return "cancelled"
        if self.completed_at and self.completed_at <= as_of:
            return "done"
        return "planned"


@dataclass
class Payment:
    payment_id: str
    contract_id: str
    work_id: Optional[str]
    purpose: str
    amount: Decimal
    status: str
    created_at: date
    paid_at: Optional[date]
    refunded_at: Optional[date]


@dataclass
class WorkLine:
    work: Work
    status: str
    price: Decimal
    paid: Decimal = ZERO
    remaining: Decimal = ZERO
    overpaid: Decimal = ZERO
    direct_paid: Decimal = ZERO
    allocated_paid: Decimal = ZERO


@dataclass
class ContractReport:
    contract: Contract
    works: list[WorkLine] = field(default_factory=list)
    obligation: Decimal = ZERO
    paid: Decimal = ZERO
    queued: Decimal = ZERO
    remaining: Decimal = ZERO
    overpaid: Decimal = ZERO
    unallocated_paid: Decimal = ZERO


def load_contracts(path: Path) -> list[Contract]:
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            rows.append(
                Contract(
                    contract_id=row["contract_id"].strip(),
                    contractor=row["contractor"].strip(),
                    amount=money(row["amount"]),
                    signed_at=parse_date(row["signed_at"]),
                )
            )
    return rows


def load_works(path: Path) -> list[Work]:
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            rows.append(
                Work(
                    work_id=row["work_id"].strip(),
                    contract_id=row["contract_id"].strip(),
                    title=row["title"].strip(),
                    price=money(row["price"]),
                    status=row["status"].strip(),
                    completed_at=parse_date(row["completed_at"]),
                    cancelled_at=parse_date(row["cancelled_at"]),
                )
            )
    return rows


def load_payments(path: Path) -> list[Payment]:
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            work_id = (row.get("work_id") or "").strip()
            rows.append(
                Payment(
                    payment_id=row["payment_id"].strip(),
                    contract_id=row["contract_id"].strip(),
                    work_id=work_id or None,
                    purpose=row["purpose"].strip(),
                    amount=money(row["amount"]),
                    status=row["status"].strip(),
                    created_at=parse_date(row["created_at"]),
                    paid_at=parse_date(row["paid_at"]),
                    refunded_at=parse_date(row["refunded_at"]),
                )
            )
    return rows


def effective_payment(payment: Payment, as_of: date) -> tuple[str, Decimal] | None:
    """Состояние платежа на дату: paid / queued / refunded. None — ещё не существовал."""
    if payment.created_at > as_of:
        return None
    paid_at = payment.paid_at
    refunded_at = payment.refunded_at
    if paid_at and paid_at <= as_of:
        if refunded_at and refunded_at <= as_of:
            return "refunded", ZERO
        return "paid", payment.amount
    return "queued", payment.amount


def allocation_order(lines: list[WorkLine]) -> list[WorkLine]:
    """Сначала закрываем принятые работы по дате приёмки, затем запланированные."""
    done = [line for line in lines if line.status == "done"]
    planned = [line for line in lines if line.status == "planned"]
    done.sort(key=lambda line: (line.work.completed_at, line.work.work_id))
    planned.sort(key=lambda line: line.work.work_id)
    return done + planned


def build_report(
    contracts: list[Contract],
    works: list[Work],
    payments: list[Payment],
    as_of: date,
) -> list[ContractReport]:
    works_by_contract: dict[str, list[Work]] = {}
    for work in works:
        works_by_contract.setdefault(work.contract_id, []).append(work)

    payments_by_contract: dict[str, list[Payment]] = {}
    for payment in payments:
        payments_by_contract.setdefault(payment.contract_id, []).append(payment)

    reports: list[ContractReport] = []
    for contract in contracts:
        report = ContractReport(contract=contract)
        contract_works = works_by_contract.get(contract.contract_id, [])
        lines_by_id: dict[str, WorkLine] = {}
        for work in contract_works:
            status = work.status_as_of(as_of)
            billable = ZERO if status == "cancelled" else work.price
            line = WorkLine(work=work, status=status, price=work.price, remaining=billable)
            report.works.append(line)
            lines_by_id[work.work_id] = line
        report.obligation = sum((line.remaining for line in report.works), ZERO)

        unallocated = ZERO
        for payment in payments_by_contract.get(contract.contract_id, []):
            effective = effective_payment(payment, as_of)
            if effective is None:
                continue
            state, amount = effective
            if state == "queued":
                report.queued += amount
                continue
            if state != "paid" or amount == ZERO:
                continue
            report.paid += amount
            if payment.work_id:
                line = lines_by_id.get(payment.work_id)
                if line is None:
                    unallocated += amount
                    continue
                line.direct_paid += amount
                if line.status == "cancelled":
                    unallocated += amount
                else:
                    capacity = line.remaining
                    applied = min(amount, capacity)
                    leftover = amount - applied
                    line.paid += applied
                    line.remaining -= applied
                    if leftover > ZERO:
                        line.overpaid += leftover
                        line.paid += leftover
            else:
                unallocated += amount

        leftover_pool = unallocated
        for line in allocation_order(report.works):
            if leftover_pool <= ZERO or line.remaining <= ZERO:
                continue
            applied = min(leftover_pool, line.remaining)
            line.paid += applied
            line.allocated_paid += applied
            line.remaining -= applied
            leftover_pool -= applied

        report.unallocated_paid = leftover_pool
        report.remaining = sum((line.remaining for line in report.works), ZERO)
        work_over = sum((line.overpaid for line in report.works), ZERO)
        report.overpaid = leftover_pool + work_over
        reports.append(report)
    return reports


def render_text(reports: list[ContractReport], as_of: date) -> str:
    lines = [
        f"Отчёт по выплатам на дату {as_of.isoformat()}",
        "Выплачено = деньги, которые уже ушли подрядчику и не возвращены.",
        "Платежи без работы распределены на работы: сначала принятые (по дате приёмки), затем запланированные.",
        "",
    ]
    grand_paid = ZERO
    grand_queued = ZERO
    grand_remaining = ZERO
    grand_obligation = ZERO

    for report in reports:
        c = report.contract
        lines.append(f"=== Договор {c.contract_id} | {c.contractor} ===")
        lines.append(f"Сумма по договору:              {fmt(c.amount)}")
        lines.append(f"К оплате по действующим работам: {fmt(report.obligation)}")
        lines.append(f"Выплачено:                       {fmt(report.paid)}")
        lines.append(f"В очереди на оплату:             {fmt(report.queued)}")
        lines.append(f"Осталось оплатить:               {fmt(report.remaining)}")
        if report.overpaid:
            lines.append(f"Переплата:                       {fmt(report.overpaid)}")
        if report.unallocated_paid:
            lines.append(
                f"Не разобрано по работам:         {fmt(report.unallocated_paid)}"
            )
        lines.append("")
        lines.append(
            f"{'Работа':<8} {'Статус':<10} {'Цена':>12} {'Выплачено':>12} {'Осталось':>12}  Название"
        )
        for line in report.works:
            extra = ""
            if line.overpaid:
                extra = f"  (переплата {fmt(line.overpaid)})"
            lines.append(
                f"{line.work.work_id:<8} {line.status:<10} {fmt(line.price):>12} "
                f"{fmt(line.paid):>12} {fmt(line.remaining):>12}  {line.work.title}{extra}"
            )
        lines.append("")
        grand_paid += report.paid
        grand_queued += report.queued
        grand_remaining += report.remaining
        grand_obligation += report.obligation

    lines.append("=== Итого ===")
    lines.append(f"К оплате по работам: {fmt(grand_obligation)}")
    lines.append(f"Выплачено:           {fmt(grand_paid)}")
    lines.append(f"В очереди:           {fmt(grand_queued)}")
    lines.append(f"Осталось оплатить:   {fmt(grand_remaining)}")
    lines.append("")
    return "\n".join(lines)


def write_csv(reports: list[ContractReport], path: Path, as_of: date) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(
            [
                "as_of",
                "level",
                "contract_id",
                "contractor",
                "work_id",
                "title",
                "status",
                "price",
                "paid",
                "remaining",
                "overpaid",
                "queued",
                "contract_amount",
                "obligation",
            ]
        )
        for report in reports:
            c = report.contract
            writer.writerow(
                [
                    as_of.isoformat(),
                    "contract",
                    c.contract_id,
                    c.contractor,
                    "",
                    "",
                    "",
                    "",
                    fmt(report.paid),
                    fmt(report.remaining),
                    fmt(report.overpaid),
                    fmt(report.queued),
                    fmt(c.amount),
                    fmt(report.obligation),
                ]
            )
            for line in report.works:
                writer.writerow(
                    [
                        as_of.isoformat(),
                        "work",
                        c.contract_id,
                        c.contractor,
                        line.work.work_id,
                        line.work.title,
                        line.status,
                        fmt(line.price),
                        fmt(line.paid),
                        fmt(line.remaining),
                        fmt(line.overpaid),
                        "",
                        "",
                        "",
                    ]
                )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Отчёт по авансам и работам")
    parser.add_argument("--date", default=DEFAULT_DATE.isoformat(), help="Дата отчёта YYYY-MM-DD")
    parser.add_argument("--data", default="data", help="Папка с CSV")
    parser.add_argument("--csv", dest="csv_path", help="Куда сохранить CSV")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    as_of = parse_date(args.date)
    if as_of is None:
        print("Некорректная дата. Ожидается YYYY-MM-DD.", file=sys.stderr)
        return 2
    data_dir = Path(args.data)
    contracts = load_contracts(data_dir / "contracts.csv")
    works = load_works(data_dir / "works.csv")
    payments = load_payments(data_dir / "payments.csv")
    reports = build_report(contracts, works, payments, as_of)
    text = render_text(reports, as_of)
    sys.stdout.write(text)
    if args.csv_path:
        write_csv(reports, Path(args.csv_path), as_of)
        print(f"CSV записан: {args.csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
