# -*- coding: utf-8 -*-
"""LuLu engineering harness — 单文件验收（对齐 mindbridge app/harness/runner.py）。

Run from lulu-agent root:
  python -m app.harness.runner --suite all
  python -m app.harness.runner --suite safety --suite routing
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


class HarnessFailure(AssertionError):
    pass


@dataclass
class CheckResult:
    name: str
    passed: bool
    details: dict = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


@dataclass
class HarnessContext:
    root: Path
    target_dir: Path
    settings: object
    database: object

    def session(self):
        return self.database.SessionLocal()


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise HarnessFailure(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run LuLu engineering harness checks.")
    parser.add_argument(
        "--suite",
        action="append",
        choices=["safety", "routing", "skills", "rag", "draft", "identity", "character", "api", "all"],
        default=None,
        help="Harness suite to run. Can be supplied multiple times.",
    )
    parser.add_argument("--json", action="store_true", help="Print only JSON output.")
    args = parser.parse_args(argv)

    configure_environment()
    context = build_context()

    suites = resolve_suites(args.suite)
    results: list[CheckResult] = []
    for name, fn in suites:
        results.append(run_check(name, fn, context))

    report = write_report(context, results)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)
    return 0 if all(result.passed for result in results) else 1


def configure_environment() -> None:
    """隔离 harness 运行：独立 sqlite + mock 友好环境变量。"""
    root = _agent_root()
    target_dir = root / "target" / "harness"
    target_dir.mkdir(parents=True, exist_ok=True)
    db_path = target_dir / "lulu-harness.sqlite3"
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{db_path}{suffix}")
        if candidate.exists():
            candidate.unlink()

    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ.setdefault("AI_PROVIDER", "mock")
    os.environ.setdefault("AGENT_FRAMEWORK", "dag_unidirectional")
    os.environ.setdefault("TTS_ENABLED", "false")
    os.environ.setdefault("ASR_ENABLED", "false")
    os.environ.setdefault("MEMORY_EXTRACT_ENABLED", "false")
    os.environ.setdefault("HARNESS_TARGET_DIR", str(target_dir))


def build_context() -> HarnessContext:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.bootstrap import init_db
    from app.core.config import get_settings
    import app.core.database as database

    get_settings.cache_clear()
    settings = get_settings()
    if getattr(database, "engine", None) is not None:
        database.engine.dispose()
    database.engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
        future=True,
    )
    database.SessionLocal = sessionmaker(bind=database.engine, autoflush=False, autocommit=False)
    init_db()
    return HarnessContext(
        root=_agent_root(),
        target_dir=_agent_root() / "target" / "harness",
        settings=settings,
        database=database,
    )


def _agent_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_suites(requested: list[str] | None) -> list[tuple[str, Callable[[HarnessContext], dict]]]:
    all_suites: list[tuple[str, Callable[[HarnessContext], dict]]] = [
        ("Safety Harness", run_safety_harness),
        ("Routing / DAG Harness", run_routing_harness),
        ("Skills Harness", run_skills_harness),
        ("Intent RAG Harness", run_rag_harness),
        ("Draft Gate Harness", run_draft_harness),
        ("Identity / Memory Harness", run_identity_harness),
        ("Character / Unlock Harness", run_character_harness),
        ("API Harness", run_api_harness),
    ]
    if not requested or "all" in requested:
        return all_suites
    aliases = {
        "safety": "Safety Harness",
        "routing": "Routing / DAG Harness",
        "skills": "Skills Harness",
        "rag": "Intent RAG Harness",
        "draft": "Draft Gate Harness",
        "identity": "Identity / Memory Harness",
        "character": "Character / Unlock Harness",
        "api": "API Harness",
    }
    names = {aliases[item] for item in requested}
    return [suite for suite in all_suites if suite[0] in names]


def run_check(name: str, fn: Callable[[HarnessContext], dict], context: HarnessContext) -> CheckResult:
    try:
        return CheckResult(name=name, passed=True, details=fn(context))
    except HarnessFailure as exc:
        return CheckResult(name=name, passed=False, failures=[str(exc)])
    except Exception as exc:
        return CheckResult(
            name=name,
            passed=False,
            failures=[f"{type(exc).__name__}: {exc}", traceback.format_exc()],
        )


def run_safety_harness(context: HarnessContext) -> dict:
    from app.services.safety import SafetyService

    safety = SafetyService()
    observed = []
    cases = [
        ("crisis-cn", "我不想活了，想结束生命。", True),
        ("crisis-en", "I want to kill myself tonight.", True),
        ("normal", "帮我唱一首歌吧", False),
        ("chat", "你好呀，今天怎么样", False),
    ]
    for case_id, text, blocked in cases:
        hit, reply = safety.check_input(text)
        expect(hit is blocked, f"{case_id}: expected blocked={blocked}, got {hit}")
        if blocked:
            expect(bool(reply), f"{case_id}: missing fallback reply")
            forbidden = ["风险等级", "HIGH_RISK", "emotionScore", "report_id"]
            expect(not any(t in (reply or "") for t in forbidden), f"{case_id}: leaked backend metadata")
        observed.append({"id": case_id, "blocked": hit})
    return {"cases": observed}


def run_routing_harness(context: HarnessContext) -> dict:
    from app.services.router import RouterService

    router = RouterService()
    router._llm_route = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("harness: skip llm"))  # type: ignore

    cases = [
        ("chat", "你好呀", "chat", []),
        ("sing", "唱一首晴天", "agents", ["sing"]),
        ("reminder", "提醒我明天开会", "agents", ["reminder"]),
        ("both-parallel", "唱首歌同时提醒我喝水", "agents", ["sing", "reminder"]),
        ("both-sequential", "唱完再提醒我吃药", "agents", ["sing", "reminder"]),
    ]
    observed = []
    for case_id, query, route, intents in cases:
        plan = router.route(query, hits=[], recent=[])
        expect(plan.route == route, f"{case_id}: route expected {route}, got {plan.route}")
        got = [s.intent_id for s in plan.steps]
        if route == "chat":
            expect(got == [], f"{case_id}: chat should have empty steps, got {got}")
        else:
            for intent in intents:
                expect(intent in got, f"{case_id}: missing intent {intent} in {got}")
        if "唱完" in query or "放完" in query:
            expect(plan.execution == "sequential", f"{case_id}: expected sequential")
        if len(got) >= 2:
            expect(bool((plan.coord_line or "").strip()), f"{case_id}: multi-intent needs coord_line")
        else:
            expect(not (plan.coord_line or "").strip(), f"{case_id}: single intent should not have coord_line")
        observed.append(
            {
                "id": case_id,
                "route": plan.route,
                "steps": got,
                "execution": plan.execution,
                "coord_line": plan.coord_line,
            }
        )
    return {"cases": observed}


def run_skills_harness(context: HarnessContext) -> dict:
    from app.agents.registry import AgentRegistry
    from app.services.skills import SkillLoader

    skills_root = context.root / "skills"
    required = ("sing", "reminder")
    found = []
    for name in required:
        skill_md = skills_root / name / "SKILL.md"
        expect(skill_md.is_file(), f"missing skills/{name}/SKILL.md")
        text = skill_md.read_text(encoding="utf-8")
        expect(len(text.strip()) > 20, f"{name} SKILL.md too short")
        found.append(name)
        loaded = SkillLoader().load_skill_md(name)
        expect(bool(loaded.strip()), f"SkillLoader failed for {name}")

    registry = AgentRegistry()
    sing = registry.profile("sing")
    rem = registry.profile("reminder")
    expect("PlaySong" in sing.tool_names, "sing missing PlaySong")
    expect("SearchSongCatalog" in sing.tool_names, "sing missing SearchSongCatalog")
    expect("ParseDateTool" in rem.tool_names, "reminder missing ParseDateTool")
    expect("FlexibleScheduleReminder" in rem.tool_names, "reminder missing FlexibleScheduleReminder")
    expect(rem.max_tool_calls >= 2, "reminder tool budget should allow ParseDate + Schedule")

    return {
        "skillDirsWithSkillMd": found,
        "singTools": list(sing.tool_names),
        "reminderTools": list(rem.tool_names),
    }


def run_rag_harness(context: HarnessContext) -> dict:
    from app.services.router import RouterService

    dataset = context.root / "data" / "intent_rag_eval.json"
    expect(dataset.is_file(), f"missing eval dataset: {dataset}")
    cases = json.loads(dataset.read_text(encoding="utf-8"))
    expect(isinstance(cases, list) and len(cases) > 0, "eval dataset empty")

    router = RouterService()
    router._llm_route = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("harness: skip llm"))  # type: ignore

    hit = 0
    details = []
    for row in cases:
        query = row["query"]
        expect_intents = list(row["expect"])
        plan = router.route(query, hits=[], recent=[])
        if plan.route == "chat":
            got = ["chat"]
        else:
            got = [s.intent_id for s in plan.steps]
        if "chat" in expect_intents:
            ok = got == ["chat"]
        else:
            ok = all(i in got for i in expect_intents)
        if ok:
            hit += 1
        details.append({"query": query, "expect": expect_intents, "got": got, "ok": ok})

    rate = hit / len(cases)
    expect(rate >= 0.75, f"heuristic intent hitRate {rate:.2f} < 0.75")
    return {"hitRate": round(rate, 3), "hit": hit, "total": len(cases), "details": details}


def run_draft_harness(context: HarnessContext) -> dict:
    from app.services.prompt import PromptService

    prompt = PromptService()
    cases = [
        ("skill-sing", "唱一首歌给我听", True),
        ("skill-reminder", "提醒我明天开会", True),
        ("chat", "今天心情一般", False),
        ("hello", "你好呀", False),
    ]
    observed = []
    for case_id, query, skip in cases:
        got = prompt.should_skip_draft(query)
        expect(got is skip, f"{case_id}: should_skip_draft expected {skip}, got {got}")
        observed.append({"id": case_id, "skip": got})

    original = context.settings.draft_gate_enabled
    try:
        context.settings.draft_gate_enabled = False
        prompt2 = PromptService()
        expect(prompt2.should_skip_draft("唱一首歌") is False, "gate disabled should not skip")
    finally:
        context.settings.draft_gate_enabled = original
    return {"cases": observed}


def run_identity_harness(context: HarnessContext) -> dict:
    from app.services.identity import DEFAULT_OWNER_PERSON_ID, IdentityService
    from app.services.character import CharacterService
    from app.services.prompt import PromptService, PromptTemplates

    db = context.session()
    try:
        identity = IdentityService(db)

        speaker = identity.resolve(None)
        expect(not speaker.is_guest, "default owner should not be guest")
        expect(speaker.person_id == DEFAULT_OWNER_PERSON_ID, "expected default owner person_id")
        expect(bool(speaker.display_name), "default owner needs display_name")

        intro = identity.intro_line(speaker)
        expect("说话" in intro, f"member intro unexpected: {intro}")
        char_res = CharacterService(db).resolve(speaker)
        character, _card = PromptService().render_character(
            card_id=char_res.card_id,
            speaker_block=intro,
        )
        expect(intro in character, "speaker_block not injected into character")

        identity.set_display_name(DEFAULT_OWNER_PERSON_ID, "小明")
        renamed = identity.resolve(None)
        expect(renamed.display_name == "小明", f"rename failed, got {renamed.display_name}")

        block = PromptTemplates.person_context_block(long_term_memory="测试长期记忆：喜欢弹钢琴")
        expect("长期记忆" in block or "测试长期记忆" in block, "person context missing long-term memory")

        original = context.settings.sole_member_fallback
        try:
            context.settings.sole_member_fallback = False
            guest = IdentityService(db).resolve(None)
            expect(guest.is_guest, "fallback off should yield guest")
            guest_intro = IdentityService(db).intro_line(guest)
            expect("不认识" in guest_intro or "客人" in guest_intro or "私事" in guest_intro, guest_intro)
        finally:
            context.settings.sole_member_fallback = original

        identity.set_display_name(DEFAULT_OWNER_PERSON_ID, "主人")
    finally:
        db.close()

    return {
        "defaultOwner": DEFAULT_OWNER_PERSON_ID,
        "renameOk": True,
        "guestPathOk": True,
    }


def run_character_harness(context: HarnessContext) -> dict:
    from app.models.entities import CharacterProgress
    from app.services.character import CharacterService
    from app.services.identity import DEFAULT_OWNER_PERSON_ID, IdentityService

    db = context.session()
    try:
        identity = IdentityService(db)
        char = CharacterService(db)

        original = context.settings.sole_member_fallback
        try:
            context.settings.sole_member_fallback = False
            guest = IdentityService(db).resolve(None)
            expect(guest.is_guest, "guest resolve failed")
            guest_res = char.resolve(guest)
            expect(guest_res.card_id == "default", f"guest card expected default, got {guest_res.card_id}")
            expect(guest_res.metrics == {}, f"guest metrics should be empty, got {guest_res.metrics}")
        finally:
            context.settings.sole_member_fallback = original

        speaker = identity.resolve(None)
        expect(speaker.person_id == DEFAULT_OWNER_PERSON_ID, "member person_id")
        fresh = char.resolve(speaker)
        expect(fresh.card_id == "default", f"new member starts default, got {fresh.card_id}")
        expect("default" in fresh.unlocked_ids, "default always unlocked")

        progress = char.get_or_create_progress(DEFAULT_OWNER_PERSON_ID)
        progress.total_turns = 30
        progress.active_days = 3
        progress.songs_played = 0
        progress.reminders_set = 0
        db.commit()

        cozy_res = char.resolve(speaker)
        expect("cozy" in cozy_res.unlocked_ids, f"cozy should unlock: {cozy_res.unlocked_ids}")
        expect(cozy_res.card_id == "default", f"user_selected keeps default until pick, got {cozy_res.card_id}")

        ok, picked = char.set_selected_card(DEFAULT_OWNER_PERSON_ID, "cozy")
        expect(ok, f"select cozy failed: {picked}")
        selected_res = char.resolve(speaker)
        expect(selected_res.card_id == "cozy", f"after select expected cozy, got {selected_res.card_id}")

        ok_bad, _msg = char.set_selected_card(DEFAULT_OWNER_PERSON_ID, "playful")
        expect(not ok_bad, "playful should not be selectable before unlock")

        unlocked, new_unlocks = char.record_turn(DEFAULT_OWNER_PERSON_ID)
        expect("default" in unlocked, "record_turn returns unlocked set")
        row = db.query(CharacterProgress).filter(CharacterProgress.person_id == DEFAULT_OWNER_PERSON_ID).first()
        expect(row is not None and row.total_turns == 31, f"total_turns expected 31, got {row.total_turns if row else None}")

        progress.songs_played = 5
        progress.total_turns = 100
        progress.active_days = 3
        db.commit()
        playful_res = char.resolve(speaker)
        expect("playful" in playful_res.unlocked_ids, "playful unlock at thresholds")
        expect(playful_res.card_id == "cozy", "user_selected sticky on cozy")

        policy_orig = char._catalog.get("active_policy")
        char._catalog["active_policy"] = "highest_unlocked"
        highest_res = char.resolve(speaker)
        expect(highest_res.card_id == "playful", f"highest_unlocked expected playful, got {highest_res.card_id}")
        char._catalog["active_policy"] = policy_orig
    finally:
        db.close()

    return {"guestDefault": True, "unlockOk": True, "userSelectedOk": True, "highestUnlockedOk": True}


def run_api_harness(context: HarnessContext) -> dict:
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()
    client = TestClient(app)
    health = client.get("/api/health")
    expect(health.status_code == 200, f"/api/health status {health.status_code}")
    body = health.json()
    expect(body.get("status") == "UP", f"/api/health body {body}")

    status = client.get("/api/agent/status")
    expect(status.status_code == 200, f"/api/agent/status status {status.status_code}")
    payload = status.json()
    expect(payload.get("framework") == "dag_unidirectional", f"framework mismatch: {payload}")
    skills = payload.get("skills") or []
    expect(isinstance(skills, list), "skills should be list")

    return {"health": body, "agentStatus": {"framework": payload.get("framework"), "skillCount": len(skills)}}


def write_report(context: HarnessContext, results: list[CheckResult]) -> dict:
    report = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "product": "lulu-agent",
        "environment": {
            "targetDir": str(context.target_dir),
            "databaseUrl": getattr(context.settings, "database_url", ""),
            "aiProvider": os.environ.get("AI_PROVIDER", "mock"),
            "agentFramework": "dag_unidirectional",
        },
        "passed": all(result.passed for result in results),
        "results": [
            {
                "name": result.name,
                "passed": result.passed,
                "details": result.details,
                "failures": result.failures,
            }
            for result in results
        ],
    }
    output = context.target_dir / "harness-report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    report["reportPath"] = str(output)
    return report


def print_report(report: dict) -> None:
    print("LuLu Engineering Harness")
    print(f"Report: {report['reportPath']}")
    print("")
    for result in report["results"]:
        status = "PASS" if result["passed"] else "FAIL"
        print(f"[{status}] {result['name']}")
        if result["passed"] and result["details"]:
            compact = json.dumps(result["details"], ensure_ascii=False, default=str)
            print(f"       {compact[:900]}")
        for failure in result["failures"]:
            print(f"       {failure}")
    print("")
    print("Overall: PASS" if report["passed"] else "Overall: FAIL")


if __name__ == "__main__":
    sys.exit(main())
