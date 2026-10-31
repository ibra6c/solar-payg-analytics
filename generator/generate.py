"""
Synthetic data generator for a Pay-As-You-Go (PAYG) off-grid solar company.

It simulates a multi-country portfolio (Senegal, Côte d'Ivoire, Ghana, Nigeria,
Kenya): products sold on credit, a daily rate paid by mobile money top-ups,
customers with different repayment behaviours, and monthly FX rates.

Everything is fake and fully reproducible (fixed seed). No real company data.

Usage:
    python generate.py --contracts 12000 --as-of 2026-09-30 --out ../data/raw
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

# --------------------------------------------------------------------------- #
# Reference data
# --------------------------------------------------------------------------- #

COUNTRIES = {
    # code: name, currency, local-per-USD at start, monthly drift, market share,
    #       repayment adjustment (+ = better payers), regions, payment channels
    "SN": dict(
        name="Senegal", currency="XOF", fx0=605.0, drift=0.000, share=0.22, adj=0.05,
        regions=["Dakar", "Thiès", "Diourbel", "Kaolack", "Saint-Louis", "Ziguinchor", "Tambacounda"],
        channels={"Wave": 0.55, "Orange Money": 0.32, "Agent cash": 0.13},
    ),
    "CI": dict(
        name="Côte d'Ivoire", currency="XOF", fx0=605.0, drift=0.000, share=0.20, adj=0.00,
        regions=["Abidjan", "Bouaké", "Daloa", "Korhogo", "San-Pédro", "Yamoussoukro"],
        channels={"Orange Money": 0.40, "MTN MoMo": 0.25, "Wave": 0.25, "Moov Money": 0.10},
    ),
    "GH": dict(
        name="Ghana", currency="GHS", fx0=12.0, drift=0.006, share=0.16, adj=-0.03,
        regions=["Greater Accra", "Ashanti", "Northern", "Volta", "Western"],
        channels={"MTN MoMo": 0.70, "Telecel Cash": 0.20, "AirtelTigo Money": 0.10},
    ),
    "NG": dict(
        name="Nigeria", currency="NGN", fx0=900.0, drift=0.008, share=0.24, adj=-0.08,
        regions=["Lagos", "Kano", "Kaduna", "Oyo", "Rivers", "Plateau"],
        channels={"OPay": 0.40, "Bank transfer": 0.30, "USSD": 0.20, "Paga": 0.10},
    ),
    "KE": dict(
        name="Kenya", currency="KES", fx0=150.0, drift=-0.003, share=0.18, adj=0.08,
        regions=["Nairobi", "Kisumu", "Nakuru", "Mombasa", "Eldoret", "Machakos"],
        channels={"M-Pesa": 0.92, "Airtel Money": 0.08},
    ),
}

PRODUCTS = [
    # id, name, category, deposit USD, daily rate USD, term days, sales weight, risk adj
    ("SHS-LITE", "Solar Home System Lite", "Solar Home System", 10.0, 0.25, 365, 0.34, 0.03),
    ("SHS-PRO", "Solar Home System Pro", "Solar Home System", 25.0, 0.45, 548, 0.26, 0.00),
    ("SHS-TV", "Solar Home System + 24\" TV", "Solar Home System", 30.0, 0.60, 730, 0.22, -0.02),
    ("ECOOK", "Electric Pressure Cooker", "Productive Use", 15.0, 0.30, 365, 0.10, 0.01),
    ("FRIDGE", "Solar Fridge Bundle", "Productive Use", 60.0, 1.10, 1095, 0.08, -0.06),
]

# Repayment profiles: share, mean extra delay after credit runs out (days),
# probability of a long gap, monthly churn hazard, top-up sizes (days of credit)
PROFILES = {
    "good": dict(share=0.55, delay=0.4, long_gap=0.01, churn=0.004, topups=[(7, 0.30), (14, 0.30), (30, 0.40)]),
    "average": dict(share=0.27, delay=1.8, long_gap=0.04, churn=0.012, topups=[(3, 0.20), (7, 0.45), (14, 0.25), (30, 0.10)]),
    "poor": dict(share=0.12, delay=5.0, long_gap=0.08, churn=0.04, topups=[(1, 0.25), (3, 0.35), (7, 0.30), (14, 0.10)]),
    "defaulter": dict(share=0.06, delay=10.0, long_gap=0.20, churn=0.25, topups=[(1, 0.40), (3, 0.40), (7, 0.20)]),
}

DEPOSIT_CREDIT_DAYS = 7  # the deposit unlocks the device for the first week
START_DATE = date(2024, 1, 1)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def weighted_choice(rng: random.Random, options: dict | list):
    """options: {value: weight} or [(value, weight), ...]."""
    items = list(options.items()) if isinstance(options, dict) else options
    values, weights = zip(*items, strict=True)
    return rng.choices(values, weights=weights, k=1)[0]


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def round_local(amount: float, currency: str) -> float:
    """Round prices the way an operator would publish them."""
    step = {"XOF": 25, "NGN": 50, "GHS": 0.5, "KES": 5}[currency]
    return max(step, round(amount / step) * step)


@dataclass
class Contract:
    contract_id: str
    customer_id: str
    product_id: str
    agent_id: str
    country: str
    currency: str
    started_on: date
    deposit: float
    daily_rate: float
    term_days: int

    @property
    def total_price(self) -> float:
        return self.deposit + self.daily_rate * self.term_days


# --------------------------------------------------------------------------- #
# Generators
# --------------------------------------------------------------------------- #

def build_fx(rng: random.Random, as_of: date) -> dict[tuple[str, date], float]:
    """Monthly local-per-USD rates: random walk with a country-specific drift."""
    fx: dict[tuple[str, date], float] = {}
    for code, c in COUNTRIES.items():
        rate, m = c["fx0"], START_DATE
        while m <= month_start(as_of):
            fx[(code, m)] = round(rate, 4)
            shock = rng.gauss(0, 0.004 if c["currency"] == "XOF" else 0.015)
            # Nigeria: one-off devaluation in early 2024
            if code == "NG" and m == date(2024, 2, 1):
                shock += 0.35
            rate *= math.exp(c["drift"] + shock)
            if c["currency"] == "XOF":  # pegged to EUR: stays in a tight band
                rate = min(max(rate, 585.0), 625.0)
            m = add_months(m, 1)
    return fx


def build_agents(rng: random.Random) -> list[dict]:
    agents = []
    for code, c in COUNTRIES.items():
        for i in range(1, 6 * len(c["regions"]) + 1):
            agents.append(dict(
                agent_id=f"AG-{code}-{i:03d}",
                country_code=code,
                region=rng.choice(c["regions"]),
                agent_type=weighted_choice(rng, {"Shop": 0.35, "Field agent": 0.55, "Partner retailer": 0.10}),
                onboarded_on=(START_DATE - timedelta(days=rng.randint(30, 900))).isoformat(),
            ))
    return agents


def signup_date(rng: random.Random, as_of: date) -> date:
    """Sales grow over time, with a December peak."""
    span = (as_of - START_DATE).days
    while True:
        d = START_DATE + timedelta(days=int(span * math.sqrt(rng.random())))
        seasonal = 1.25 if d.month == 12 else (0.85 if d.month in (7, 8) else 1.0)
        if rng.random() < seasonal / 1.25:
            return d


def simulate_payments(rng: random.Random, k: Contract, profile: dict, risk_adj: float,
                      as_of: date, channels: dict) -> list[dict]:
    """Event-based simulation of mobile-money top-ups for one contract."""
    payments = []
    paid = 0.0

    def pay(day: date, amount: float):
        nonlocal paid
        amount = min(amount, k.total_price - paid)
        if amount <= 0:
            return
        paid += amount
        ts = datetime.combine(day, datetime.min.time()) + timedelta(
            seconds=rng.randint(6 * 3600, 22 * 3600))
        payments.append(dict(
            contract_id=k.contract_id,
            paid_at=ts.isoformat(sep=" "),
            amount_local=round(amount, 2),
            currency_code=k.currency,
            channel=weighted_choice(rng, channels),
        ))

    pay(k.started_on, k.deposit)
    credit_until = k.started_on + timedelta(days=DEPOSIT_CREDIT_DAYS)

    # better/worse behaviour depending on country and product
    delay_factor = max(0.3, 1 - 4 * risk_adj)
    churn_factor = max(0.2, 1 - 6 * risk_adj)

    while paid < k.total_price:
        days = weighted_choice(rng, profile["topups"])
        # monthly churn hazard, scaled to the length of this top-up cycle
        if rng.random() < profile["churn"] * churn_factor * days / 30:
            break
        delay = rng.expovariate(1 / (profile["delay"] * delay_factor)) if profile["delay"] else 0
        if rng.random() < profile["long_gap"]:
            delay += rng.randint(20, 75)
        # good payers often top up *before* credit runs out
        early = rng.randint(0, 2) if profile is PROFILES["good"] else 0
        pay_day = credit_until + timedelta(days=round(delay) - early)
        pay_day = max(pay_day, k.started_on + timedelta(days=1))
        if pay_day > as_of:
            break
        pay(pay_day, days * k.daily_rate)
        credit_until = max(credit_until, pay_day) + timedelta(days=days)

    return payments


def generate(n_contracts: int, as_of: date, seed: int) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    fx = build_fx(rng, as_of)
    agents = build_agents(rng)
    agents_by_country: dict[str, list[dict]] = {}
    for a in agents:
        agents_by_country.setdefault(a["country_code"], []).append(a)

    customers, contracts, payments = [], [], []
    shares = {code: c["share"] for code, c in COUNTRIES.items()}
    product_weights = [(p, p[6]) for p in PRODUCTS]

    for i in range(1, n_contracts + 1):
        code = weighted_choice(rng, shares)
        c = COUNTRIES[code]
        product = weighted_choice(rng, product_weights)
        pid, _, _, dep_usd, rate_usd, term, _, prod_adj = product
        agent = rng.choice(agents_by_country[code])
        started = signup_date(rng, as_of)
        fx_rate = fx[(code, month_start(started))]

        customer_id = f"CU-{i:06d}"
        customers.append(dict(
            customer_id=customer_id,
            country_code=code,
            region=agent["region"] if rng.random() < 0.85 else rng.choice(c["regions"]),
            gender=weighted_choice(rng, {"F": 0.46, "M": 0.54}),
            age_band=weighted_choice(rng, {"18-24": 0.12, "25-34": 0.33, "35-44": 0.28, "45-54": 0.17, "55+": 0.10}),
            occupation=weighted_choice(rng, {"Farmer": 0.38, "Trader": 0.27, "Salaried": 0.12,
                                              "Artisan": 0.13, "Other": 0.10}),
            registered_at=datetime.combine(started, datetime.min.time()).isoformat(sep=" "),
        ))

        k = Contract(
            contract_id=f"CT-{i:06d}",
            customer_id=customer_id,
            product_id=pid,
            agent_id=agent["agent_id"],
            country=code,
            currency=c["currency"],
            started_on=started,
            deposit=round_local(dep_usd * fx_rate, c["currency"]),
            daily_rate=round_local(rate_usd * fx_rate, c["currency"]),
            term_days=term,
        )
        contracts.append(dict(
            contract_id=k.contract_id, customer_id=k.customer_id, product_id=k.product_id,
            agent_id=k.agent_id, country_code=code, currency_code=k.currency,
            started_on=k.started_on.isoformat(), deposit_local=k.deposit,
            daily_rate_local=k.daily_rate, term_days=k.term_days,
        ))

        profile = PROFILES[weighted_choice(rng, {n: p["share"] for n, p in PROFILES.items()})]
        payments.extend(simulate_payments(rng, k, profile, c["adj"] + prod_adj, as_of, c["channels"]))

    # payment ids + a realistic data-quality issue: ~0.4% duplicated webhook events
    payments.sort(key=lambda p: p["paid_at"])
    out_payments = []
    for n, p in enumerate(payments, start=1):
        p = dict(payment_id=f"PM-{n:08d}", provider_reference=f"TX{rng.getrandbits(48):012X}", **p)
        out_payments.append(p)
        if rng.random() < 0.004:
            dup = dict(p)
            dup["payment_id"] = f"PM-{n:08d}-R"
            out_payments.append(dup)

    for p in out_payments:
        p["ingested_at"] = p["paid_at"]

    return dict(
        countries=[dict(country_code=k, country_name=v["name"], currency_code=v["currency"])
                   for k, v in COUNTRIES.items()],
        fx_rates=[dict(country_code=k[0], currency_code=COUNTRIES[k[0]]["currency"],
                       rate_month=k[1].isoformat(), local_per_usd=v) for k, v in fx.items()],
        products=[dict(product_id=p[0], product_name=p[1], category=p[2], deposit_usd=p[3],
                       daily_rate_usd=p[4], term_days=p[5]) for p in PRODUCTS],
        agents=agents,
        customers=customers,
        contracts=contracts,
        payments=out_payments,
    )


def write_csv(tables: dict[str, list[dict]], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        with open(out / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"  {name:<10} {len(rows):>9,} rows")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contracts", type=int, default=12_000)
    ap.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 9, 30))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "data" / "raw")
    args = ap.parse_args()

    print(f"Generating {args.contracts:,} contracts up to {args.as_of} (seed={args.seed})")
    write_csv(generate(args.contracts, args.as_of, args.seed), args.out)


if __name__ == "__main__":
    main()
