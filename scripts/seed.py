"""Seeds one organization, three users (agent, lead, admin), the action registry, and (unless
--skip-knowledge is passed) the SOP documents under config/seed/knowledge/ via knowledge_ingest.

Usage: python scripts/seed.py [--reset] [--skip-knowledge]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

from libs.platform.config import get_settings
from libs.platform.db.models import Base
from libs.platform.db.repositories import ActionRegistryEntryRepo, AppUserRepo, CustomerRepo, OrganizationRepo
from libs.platform.db.session import build_engine, init_db, session_scope
from libs.platform.registry import build_ports

_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
_KNOWLEDGE_SEED_DIR = _CONFIG_DIR / "seed" / "knowledge"


def _seed_org_and_users(session) -> str:
    org = OrganizationRepo(session).create(name="Acme Telecom")
    users = AppUserRepo(session)
    users.create(org_id=org.id, username="agent1", role="agent", email="agent1@example.com")
    users.create(org_id=org.id, username="lead1", role="lead", email="lead1@example.com")
    users.create(org_id=org.id, username="admin1", role="admin", email="admin1@example.com")
    CustomerRepo(session).create(org_id=org.id, name="Demo Customer", segment="standard")
    return org.id


def _seed_action_registry(session) -> int:
    data = yaml.safe_load((_CONFIG_DIR / "action_registry.yaml").read_text(encoding="utf-8"))
    repo = ActionRegistryEntryRepo(session)
    count = 0
    for entry in data.get("actions", []):
        permits = entry.get("permits", {})
        impact_limits = {k: v for k, v in permits.items() if k.startswith("max_")}
        repo.upsert(
            action_id=entry["action_id"],
            department=entry["department"],
            description=entry["description"],
            mapped_faults=entry.get("faults", []),
            requires_supervisor=not entry.get("idempotent", True),
            enabled=True,
            requires_fields=permits.get("requires_fields", []),
            impact_limits=impact_limits,
        )
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="drop and recreate all tables first")
    parser.add_argument("--skip-knowledge", action="store_true", help="skip ingesting config/seed/knowledge/*.md")
    args = parser.parse_args()

    settings = get_settings()
    engine = build_engine(settings.database_url)

    if args.reset:
        Base.metadata.drop_all(engine)
    init_db(engine)

    with session_scope(engine) as session:
        org_id = _seed_org_and_users(session)
        n_actions = _seed_action_registry(session)

    print(f"seeded organization {org_id}, 3 users, 1 customer, {n_actions} action registry entries")

    if not args.skip_knowledge and _KNOWLEDGE_SEED_DIR.exists():
        from services.knowledge_ingest.handler import ingest_directory

        ports = build_ports(settings)
        reports = ingest_directory(ports, engine, org_id=org_id, directory=_KNOWLEDGE_SEED_DIR)
        total_chunks = sum(r.num_chunks for r in reports)
        print(f"ingested {len(reports)} SOP documents, {total_chunks} chunks")


if __name__ == "__main__":
    main()
