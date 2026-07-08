"""Synthetic dataset generation for agentic-data-harness.

Generates three domains with intentional schema traps:
- sales_analytics: country_code not country names, total_cents not total_amount
- support_tickets: account_id not customer_id
- product_usage: plan_code not plan names, string timestamps
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
from rich.console import Console

console = Console()

BENCHMARK_DATE = date(2026, 6, 30)

BENCHMARK_METADATA_SCHEMA = """
CREATE TABLE IF NOT EXISTS benchmark_metadata (
    key VARCHAR PRIMARY KEY,
    value VARCHAR NOT NULL
);
"""

DOMAIN_TABLES: dict[str, list[str]] = {
    "sales_analytics": ["customers", "orders", "refunds"],
    "support_tickets": ["accounts", "tickets"],
    "product_usage": ["users", "events"],
}
"""Maps domain names to their benchmark data tables for safe reset operations."""


class DatasetAlreadyExistsError(RuntimeError):
    """Raised when dataset generation would append into an existing benchmark dataset."""


# ─────────────────────────────────────────────
# Domain schemas
# ─────────────────────────────────────────────

SALES_ANALYTICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    country_code VARCHAR(2) NOT NULL,
    segment VARCHAR DEFAULT 'midmarket'
);

CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    order_date VARCHAR NOT NULL,
    total_cents INTEGER NOT NULL,
    status VARCHAR DEFAULT 'completed'
);

CREATE TABLE IF NOT EXISTS refunds (
    refund_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    refund_cents INTEGER NOT NULL,
    refund_date VARCHAR NOT NULL,
    reason VARCHAR
);
"""

SUPPORT_TICKETS_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    segment VARCHAR NOT NULL,
    country_code VARCHAR(2)
);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    priority VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    resolved_at VARCHAR,
    category VARCHAR DEFAULT 'general',
    satisfaction_score INTEGER
);
"""

PRODUCT_USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    plan_code VARCHAR NOT NULL,
    signup_date VARCHAR NOT NULL,
    region_code VARCHAR(2)
);

CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    event_name VARCHAR NOT NULL,
    event_ts VARCHAR NOT NULL,
    feature VARCHAR,
    duration_ms INTEGER
);
"""


@dataclass
class SalesAnalyticsData:
    customers: list[dict] = field(default_factory=list)
    orders: list[dict] = field(default_factory=list)
    refunds: list[dict] = field(default_factory=list)


@dataclass
class SupportTicketsData:
    accounts: list[dict] = field(default_factory=list)
    tickets: list[dict] = field(default_factory=list)


@dataclass
class ProductUsageData:
    users: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)


class DataGenerator:
    """Generates synthetic benchmark datasets with intentional traps."""

    def __init__(self, db_path: str | Path, seed: int = 42):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.seed = seed
        self.rng = random.Random(seed)

    def generate_all(self, domains: list[str] | None = None, reset: bool = False) -> None:
        """Generate all domains or a subset."""
        self.rng = random.Random(self.seed)
        all_domains = list(DOMAIN_TABLES)
        targets = domains or all_domains

        conn = duckdb.connect(str(self.db_path))
        try:
            self._ensure_generation_target_is_safe(conn, targets=targets, reset=reset)

            if reset:
                for domain in targets:
                    self._drop_domain_tables(conn, domain)

            for domain in targets:
                if domain == "sales_analytics":
                    self._generate_sales(conn)
                elif domain == "support_tickets":
                    self._generate_support(conn)
                elif domain == "product_usage":
                    self._generate_product(conn)
                else:
                    console.print(f"[yellow]Unknown domain: {domain}[/]")

            conn.execute(BENCHMARK_METADATA_SCHEMA)
            self._write_benchmark_metadata(conn)
        finally:
            conn.close()

    def _generate_sales(self, conn: duckdb.DuckDBPyConnection):
        console.print("[bold]Generating sales_analytics[/]")
        conn.execute(SALES_ANALYTICS_SCHEMA)

        # Countries — use codes, NOT names (this is the trap)
        countries = ["NL", "DE", "FR", "ES", "IT", "BE", "UK", "SE", "DK", "PL"]
        segments = ["enterprise", "midmarket", "smb"]

        # Generate customers
        customers = [
            {
                "customer_id": i,
                "name": f"Customer_{i}",
                "country_code": self.rng.choice(countries),
                "segment": self.rng.choice(segments),
            }
            for i in range(1, 51)
        ]

        # Generate orders — Q1-Q2 2026
        orders = []
        order_id = 1
        base_date = datetime(2026, 1, 1)
        for _ in range(200):
            cust = self.rng.choice(customers)
            offset = self.rng.randint(0, 180)
            order_date = (base_date + timedelta(days=offset)).strftime("%Y-%m-%d")

            # total_cents — trap: NOT total_amount (cents, not euros)
            total_cents = self.rng.randint(500, 500000)

            orders.append(
                {
                    "order_id": order_id,
                    "customer_id": cust["customer_id"],
                    "order_date": order_date,
                    "total_cents": total_cents,
                    "status": self.rng.choice(
                        ["completed", "completed", "completed", "pending", "cancelled"]
                    ),
                }
            )
            order_id += 1

        # Generate refunds — ~15% of orders
        refunds = []
        refund_id = 1
        for order in orders:
            if self.rng.random() < 0.15:
                refund_amount = int(order["total_cents"] * self.rng.uniform(0.1, 0.5))
                order_date = datetime.strptime(order["order_date"], "%Y-%m-%d")
                refund_date = (order_date + timedelta(days=self.rng.randint(1, 30))).strftime(
                    "%Y-%m-%d"
                )
                refunds.append(
                    {
                        "refund_id": refund_id,
                        "order_id": order["order_id"],
                        "refund_cents": refund_amount,
                        "refund_date": refund_date,
                        "reason": self.rng.choice(
                            ["customer_request", "damaged", "wrong_item", None]
                        ),
                    }
                )
                refund_id += 1

        # Insert
        for c in customers:
            conn.execute(
                "INSERT INTO customers VALUES (?, ?, ?, ?)",
                [c["customer_id"], c["name"], c["country_code"], c["segment"]],
            )
        for o in orders:
            conn.execute(
                "INSERT INTO orders VALUES (?, ?, ?, ?, ?)",
                [o["order_id"], o["customer_id"], o["order_date"], o["total_cents"], o["status"]],
            )
        for r in refunds:
            conn.execute(
                "INSERT INTO refunds VALUES (?, ?, ?, ?, ?)",
                [r["refund_id"], r["order_id"], r["refund_cents"], r["refund_date"], r["reason"]],
            )

        console.print(f"  customers: {len(customers)} rows")
        console.print(f"  orders: {len(orders)} rows")
        console.print(f"  refunds: {len(refunds)} rows")
        console.print(
            "  [dim]traps: country_code (not country names), total_cents (not total_amount), string dates[/]"
        )

    def _generate_support(self, conn: duckdb.DuckDBPyConnection):
        console.print("[bold]Generating support_tickets[/]")
        conn.execute(SUPPORT_TICKETS_SCHEMA)

        segments = ["enterprise", "midmarket", "smb"]
        countries = ["NL", "DE", "FR", "ES", "UK", "US"]

        # Generate accounts
        accounts = [
            {
                "account_id": i,
                "name": f"Account_{i}",
                "segment": self.rng.choice(segments),
                "country_code": self.rng.choice(countries),
            }
            for i in range(1, 31)
        ]

        # Generate tickets — Q1-Q2 2026
        tickets = []
        priorities = ["P0", "P1", "P2", "P3"]
        categories = ["general", "billing", "technical", "access", "feature_request"]
        base_date = datetime(2026, 1, 1)

        for ticket_id in range(1, 101):
            account = self.rng.choice(accounts)
            offset = self.rng.randint(0, 180)
            created_at = (base_date + timedelta(days=offset)).strftime("%Y-%m-%d")

            resolved_at = None
            if self.rng.random() < 0.7:
                resolve_offset = self.rng.randint(1, 14)
                resolved_at = (
                    datetime.strptime(created_at, "%Y-%m-%d") + timedelta(days=resolve_offset)
                ).strftime("%Y-%m-%d")

            tickets.append(
                {
                    "ticket_id": ticket_id,
                    "account_id": account["account_id"],
                    "priority": self.rng.choice(priorities),
                    "created_at": created_at,
                    "resolved_at": resolved_at,
                    "category": self.rng.choice(categories),
                    "satisfaction_score": self.rng.randint(1, 5) if resolved_at else None,
                }
            )

        for a in accounts:
            conn.execute(
                "INSERT INTO accounts VALUES (?, ?, ?, ?)",
                [a["account_id"], a["name"], a["segment"], a["country_code"]],
            )
        for t in tickets:
            conn.execute(
                "INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    t["ticket_id"],
                    t["account_id"],
                    t["priority"],
                    t["created_at"],
                    t["resolved_at"],
                    t["category"],
                    t["satisfaction_score"],
                ],
            )

        console.print(f"  accounts: {len(accounts)} rows")
        console.print(f"  tickets: {len(tickets)} rows")
        console.print("  [dim]traps: account_id (not customer_id), string timestamps[/]")

    def _generate_product(self, conn: duckdb.DuckDBPyConnection):
        console.print("[bold]Generating product_usage[/]")
        conn.execute(PRODUCT_USAGE_SCHEMA)

        plans = ["free", "pro", "ent"]
        regions = ["NL", "DE", "FR", "ES", "US", "UK", "SE"]
        event_names = [
            "login",
            "create_report",
            "export_data",
            "invite_user",
            "view_dashboard",
            "edit_profile",
            "run_analysis",
        ]
        features = ["reports", "dashboards", "exports", "team", "analytics", "settings"]

        # Generate users
        users = [
            {
                "user_id": i,
                "plan_code": self.rng.choices(plans, weights=[0.4, 0.35, 0.25])[0],
                "signup_date": (
                    datetime(2025, 6, 1) + timedelta(days=self.rng.randint(0, 365))
                ).strftime("%Y-%m-%d"),
                "region_code": self.rng.choice(regions),
            }
            for i in range(1, 41)
        ]

        # Generate events for the fixed benchmark window ending on BENCHMARK_DATE
        events = []
        event_id = 1
        base_date = datetime.combine(BENCHMARK_DATE, datetime.min.time()) - timedelta(days=60)
        for _ in range(500):
            user = self.rng.choice(users)
            offset = self.rng.randint(0, 60)
            event_ts = (
                base_date
                + timedelta(
                    days=offset, hours=self.rng.randint(0, 23), minutes=self.rng.randint(0, 59)
                )
            ).strftime("%Y-%m-%d %H:%M:%S")
            events.append(
                {
                    "event_id": event_id,
                    "user_id": user["user_id"],
                    "event_name": self.rng.choice(event_names),
                    "event_ts": event_ts,
                    "feature": self.rng.choice(features),
                    "duration_ms": self.rng.randint(50, 30000),
                }
            )
            event_id += 1

        self._align_relative_time_product_events(users, events)

        for u in users:
            conn.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?)",
                [u["user_id"], u["plan_code"], u["signup_date"], u["region_code"]],
            )
        for e in events:
            conn.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
                [
                    e["event_id"],
                    e["user_id"],
                    e["event_name"],
                    e["event_ts"],
                    e["feature"],
                    e["duration_ms"],
                ],
            )

        console.print(f"  users: {len(users)} rows")
        console.print(f"  events: {len(events)} rows")
        console.print("  [dim]traps: plan_code (not plan names), string timestamps[/]")

    # ── Idempotency & metadata helpers ──

    def _align_relative_time_product_events(
        self,
        users: list[dict],
        events: list[dict],
    ) -> None:
        """Anchor pro-plan activity to the benchmark-relative 30-day window."""
        plan_by_user_id = {user["user_id"]: user["plan_code"] for user in users}
        window_start = datetime.combine(BENCHMARK_DATE, datetime.min.time()) - timedelta(days=30)
        moved_events = 0

        for event in events:
            if plan_by_user_id[event["user_id"]] != "pro":
                continue

            event_ts = datetime.strptime(event["event_ts"], "%Y-%m-%d %H:%M:%S")
            if event_ts >= window_start:
                continue

            aligned_ts = window_start + timedelta(
                hours=moved_events // 60, minutes=moved_events % 60
            )
            event["event_ts"] = aligned_ts.strftime("%Y-%m-%d %H:%M:%S")
            moved_events += 1

    def _ensure_generation_target_is_safe(
        self,
        conn: duckdb.DuckDBPyConnection,
        targets: list[str],
        reset: bool,
    ) -> None:
        """Raise an error if target tables already have rows and reset is not requested."""
        if reset:
            return
        existing = self._existing_nonempty_tables(conn, targets)
        if existing:
            joined = ", ".join(existing)
            raise DatasetAlreadyExistsError(
                f"Benchmark tables already contain rows: {joined}. "
                "Re-run with reset=True or pass --reset in the CLI."
            )

    def _existing_nonempty_tables(
        self,
        conn: duckdb.DuckDBPyConnection,
        targets: list[str],
    ) -> list[str]:
        """Return list of target benchmark tables that already have rows."""
        all_tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        nonempty: list[str] = []
        for domain in targets:
            for table in DOMAIN_TABLES.get(domain, []):
                if table in all_tables:
                    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                    if count and count[0] > 0:
                        nonempty.append(table)
        return nonempty

    def _drop_domain_tables(
        self,
        conn: duckdb.DuckDBPyConnection,
        domain: str,
    ) -> None:
        """Drop benchmark tables for a single domain (idempotent)."""
        for table in DOMAIN_TABLES.get(domain, []):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute("DROP TABLE IF EXISTS benchmark_metadata")

    def _write_benchmark_metadata(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Upsert benchmark date and seed into the metadata table."""
        conn.execute("DELETE FROM benchmark_metadata WHERE key IN ('benchmark_date', 'seed')")
        conn.execute(
            "INSERT INTO benchmark_metadata VALUES (?, ?)",
            ["benchmark_date", BENCHMARK_DATE.isoformat()],
        )
        conn.execute(
            "INSERT INTO benchmark_metadata VALUES (?, ?)",
            ["seed", str(self.seed)],
        )
