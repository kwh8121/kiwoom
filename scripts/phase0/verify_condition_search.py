"""0단계 연동 검증: 키움 조건검색(ka10171 CNSRLST / ka10172 CNSRREQ) 조회 전용 측정.

실행 (kiwoomcli가 설치된 uv tool 환경의 Python 사용):
    ~/.local/share/uv/tools/kwcli/bin/python scripts/phase0/verify_condition_search.py

- keyring 비밀번호는 시작 시 한 번 입력한다.
- CNSRLST, CNSRREQ(search_type=0)만 전송한다. 실시간 등록·주문 API는 호출하지 않는다.
- 토큰·앱키는 출력 파일에 기록하지 않는다.

v0.2: 1차 실행(20261017-134804)에서 CNSRREQ 1건에 응답 외에 `{"trnm":"CNSRREQ"}`만 있는
메시지(bare)가 추가로 오는 것을 확인했다. 요청은 한 번에 하나만 보내고, 응답은 `seq`로 대응시키며,
수신한 모든 메시지를 도착 시각과 함께 기록한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from kiwoom import get_ws_client
from kiwoom.core.errors import embedded_return_code, normalize_return_code

KST = timezone(timedelta(hours=9))
WS_PATH = "/api/dostk/websocket"
ALLOWED_TRNM = {"CNSRLST", "CNSRREQ"}
RATE_LIMIT_CODES = {105110, 1700, 1701, 1702}
CODE_RE = re.compile(r"^([A-Z]?)([0-9A-Z]{6})$")
SCRIPT_VERSION = "0.2"


def now_kst() -> datetime:
    return datetime.now(KST)


class Recorder:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.events = (out_dir / "events.jsonl").open("w", encoding="utf-8")
        self.summary: dict[str, Any] = {}
        self.fixtures: dict[str, Any] = {}

    def event(self, **payload: Any) -> None:
        payload.setdefault("ts", now_kst().isoformat())
        self.events.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.events.flush()

    def close(self) -> None:
        self.events.close()
        (self.out_dir / "summary.json").write_text(json.dumps(self.summary, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.out_dir / "fixtures.json").write_text(json.dumps(self.fixtures, ensure_ascii=False, indent=2), encoding="utf-8")


def return_code_of(msg: dict[str, Any]) -> int | None:
    code = normalize_return_code(msg.get("return_code"))
    if code not in (None, 0):
        embedded = embedded_return_code(msg.get("return_msg"))
        if embedded is not None:
            return embedded
    return code


def classify(msg: Any) -> str:
    if not isinstance(msg, dict):
        return "non_dict"
    keys = set(msg.keys())
    if keys == {"trnm"}:
        return "bare"
    code = return_code_of(msg)
    if code not in (None, 0):
        return "error"
    if "seq" in msg:
        return "data"
    if "data" in msg:
        return "list"
    return "other"


def summarize_message(msg: Any) -> dict[str, Any]:
    if not isinstance(msg, dict):
        return {"type": type(msg).__name__, "value": str(msg)[:200]}
    rows = msg.get("data")
    return {
        "trnm": msg.get("trnm"),
        "seq": msg.get("seq"),
        "return_code": msg.get("return_code"),
        "return_msg": msg.get("return_msg"),
        "cont_yn": msg.get("cont_yn"),
        "next_key_len": len(str(msg.get("next_key") or "")),
        "data_type": type(rows).__name__,
        "data_len": len(rows) if isinstance(rows, list) else None,
        "keys": sorted(msg.keys()),
    }


def normalize_code(raw: str) -> tuple[str | None, str | None]:
    match = CODE_RE.match(raw)
    if not match:
        return None, None
    return match.group(1) or "", match.group(2)


class Session:
    def __init__(self, profile: str, rec: Recorder, *, label: str, timeout: float = 15.0, drain: float = 0.3) -> None:
        self.profile = profile
        self.rec = rec
        self.label = label
        self.timeout = timeout
        self.drain = drain
        self.client: Any = None
        self.request_count = 0
        self.bare_count = 0

    async def __aenter__(self) -> "Session":
        self.client = get_ws_client(profile=self.profile)
        t0 = time.monotonic()
        await self.client.connect(api_url=WS_PATH)
        self.rec.event(kind="connect", profile=self.profile, mode=self.client.auth.mode, label=self.label, elapsed_ms=round((time.monotonic() - t0) * 1000))
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self.client is not None:
            await self.client.close()

    async def _recv(self, timeout: float) -> Any:
        return await asyncio.wait_for(self.client.recv(), timeout=timeout)

    def _log(self, phase: str, label: str, msg: Any, t_send: float) -> str:
        cls = classify(msg)
        if cls == "bare":
            self.bare_count += 1
        self.rec.event(
            kind="msg",
            phase=phase,
            cls=cls,
            profile=self.profile,
            label=label,
            offset_ms=round((time.monotonic() - t_send) * 1000),
            **summarize_message(msg),
        )
        return cls

    async def request(self, body: dict[str, Any], *, label: str, drain: float | None = None) -> tuple[dict[str, Any], int]:
        """요청 1건을 보내고 대응 응답을 반환한다. 응답 후 drain 동안 추가 메시지를 기록한다."""
        trnm = body.get("trnm")
        if trnm not in ALLOWED_TRNM:
            raise RuntimeError(f"허용되지 않은 trnm: {trnm}")
        if trnm == "CNSRREQ" and body.get("search_type") != "0":
            raise RuntimeError("search_type=0(1회 조회)만 허용")
        want_seq = str(body.get("seq")) if trnm == "CNSRREQ" else None
        t_send = time.monotonic()
        await self.client.send(body)
        self.request_count += 1
        self.rec.event(kind="send", profile=self.profile, label=label, request={k: v for k, v in body.items() if k != "next_key"})
        matched: dict[str, Any] | None = None
        while matched is None:
            remaining = self.timeout - (time.monotonic() - t_send)
            if remaining <= 0:
                raise TimeoutError(f"{label}: {self.timeout:g}s 안에 {trnm} 응답 없음")
            msg = await self._recv(remaining)
            cls = self._log("wait", label, msg, t_send)
            if not isinstance(msg, dict) or str(msg.get("trnm", "")).upper() != trnm:
                continue
            if cls == "error":
                matched = msg
            elif trnm == "CNSRLST" and cls == "list":
                matched = msg
            elif trnm == "CNSRREQ" and cls == "data" and str(msg.get("seq")) == want_seq:
                matched = msg
        elapsed = round((time.monotonic() - t_send) * 1000)
        drain_s = self.drain if drain is None else drain
        if drain_s > 0:
            end = time.monotonic() + drain_s
            while (left := end - time.monotonic()) > 0:
                try:
                    msg = await self._recv(left)
                except TimeoutError:
                    break
                self._log("drain", label, msg, t_send)
        return matched, elapsed

    async def list_conditions(self, *, label: str) -> list[dict[str, str]]:
        msg, _ = await self.request({"trnm": "CNSRLST"}, label=label)
        out = []
        for row in msg.get("data") or []:
            if isinstance(row, dict):
                out.append({"seq": str(row.get("seq", "")).strip(), "name": str(row.get("name", "")).strip()})
            elif isinstance(row, (list, tuple)) and len(row) >= 2:
                out.append({"seq": str(row[0]).strip(), "name": str(row[1]).strip()})
        return out

    async def search(
        self,
        seq: str,
        *,
        label: str,
        stex_tp: str = "K",
        max_pages: int = 100,
        rate_limit_retries: int = 4,
        drain: float | None = None,
    ) -> dict[str, Any]:
        t0 = time.monotonic()
        started_at = now_kst().isoformat()
        pages: list[dict[str, Any]] = []
        raw_codes: list[str] = []
        sample_rows: list[Any] = []
        change_rates: list[str] = []
        next_key: str | None = None
        complete = False
        error: dict[str, Any] | None = None
        retries = 0
        first_message = None
        while len(pages) < max_pages:
            body: dict[str, Any] = {"trnm": "CNSRREQ", "seq": seq, "search_type": "0", "stex_tp": stex_tp}
            if next_key:
                body["cont_yn"] = "Y"
                body["next_key"] = next_key
            msg, elapsed = await self.request(body, label=f"{label}#p{len(pages) + 1}", drain=drain)
            code = return_code_of(msg)
            if code in RATE_LIMIT_CODES and retries < rate_limit_retries:
                retries += 1
                await asyncio.sleep(0.5 * 2**retries)
                continue
            if code not in (None, 0):
                error = {"return_code": msg.get("return_code"), "resolved": code, "return_msg": msg.get("return_msg")}
                break
            first_message = first_message or msg
            rows = msg.get("data") or []
            for row in rows if isinstance(rows, list) else []:
                if isinstance(row, dict):
                    raw_codes.append(str(row.get("9001", "")).strip())
                    if row.get("12") is not None:
                        change_rates.append(str(row["12"]))
                    if len(sample_rows) < 2:
                        sample_rows.append(row)
            pages.append({"rows": len(rows) if isinstance(rows, list) else 0, "data_type": type(msg.get("data")).__name__, "cont_yn": msg.get("cont_yn"), "next_key_len": len(str(msg.get("next_key") or "")), "elapsed_ms": elapsed})
            if msg.get("cont_yn") == "Y":
                next_key = msg.get("next_key")
                if not next_key:
                    error = {"app": "CONT_Y_WITHOUT_NEXT_KEY"}
                    break
                continue
            complete = True
            break
        else:
            error = {"app": "MAX_PAGES_EXCEEDED"}

        prefixes: Counter[str] = Counter()
        invalid, normalized = [], []
        for raw in raw_codes:
            prefix, code6 = normalize_code(raw)
            if code6 is None:
                invalid.append(raw)
                continue
            prefixes[prefix or "<none>"] += 1
            normalized.append(code6)
        result = {
            "seq": seq,
            "stex_tp": stex_tp,
            "started_at": started_at,
            "elapsed_ms": round((time.monotonic() - t0) * 1000),
            "pages": pages,
            "page_count": len(pages),
            "complete": complete,
            "error": error,
            "rate_limit_retries": retries,
            "row_count": len(raw_codes),
            "unique_count": len(set(normalized)),
            "duplicate_rows": len(normalized) - len(set(normalized)),
            "prefixes": dict(prefixes),
            "invalid_codes": invalid[:20],
            "non_digit_codes": sorted({c for c in normalized if not c.isdigit()}),
            "change_rate_lengths": dict(Counter(len(v) for v in change_rates)),
            "negative_change_rate_samples": [v for v in change_rates if v.startswith("-")][:3],
            "codes": sorted(set(normalized)),
        }
        self.rec.event(kind="search_result", profile=self.profile, label=label, **{k: v for k, v in result.items() if k != "codes"})
        if first_message is not None:
            result["_first_message"] = first_message
        return result


def public(result: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in result.items() if not k.startswith("_")}


async def guarded(rec: Recorder, name: str, coro: Any) -> Any:
    print(f"▶ {name}", flush=True)
    try:
        value = await coro
        rec.summary.setdefault("tests", {})[name] = {"status": "ok", "result": value}
        return value
    except Exception as exc:  # noqa: BLE001
        rec.event(kind="exception", test=name, error_type=type(exc).__name__, error=str(exc))
        rec.summary.setdefault("tests", {})[name] = {"status": "error", "error_type": type(exc).__name__, "error": str(exc)}
        print(f"  ✗ {name}: {type(exc).__name__}: {exc}", flush=True)
        return None


async def test_sweep(rec: Recorder, profile: str, delay: float) -> dict[str, Any]:
    async with Session(profile, rec, label="sweep") as s:
        conditions = await s.list_conditions(label="sweep:list")
        results = {}
        for cond in conditions:
            r = await s.search(cond["seq"], label=f"sweep:{cond['seq']}")
            if r.get("_first_message") and r["row_count"] > 0:
                bucket = rec.fixtures.setdefault(profile, {})
                if len(bucket) < 3:
                    bucket[cond["seq"]] = r["_first_message"]
            results[cond["seq"]] = {"name": cond["name"], **public(r)}
            print(f"  {profile} seq={cond['seq']:>3} {cond['name']}: rows={r['row_count']} pages={r['page_count']} complete={r['complete']} err={r['error']} retries={r['rate_limit_retries']}", flush=True)
            await asyncio.sleep(delay)
        return {"conditions": conditions, "results": results, "requests": s.request_count, "bare_messages": s.bare_count}


async def test_without_list(rec: Recorder, profile: str, seq: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    async with Session(profile, rec, label="nolist", timeout=10) as s:
        try:
            r = await s.search(seq, label="nolist:search", max_pages=1)
            out["without_list"] = public(r)
        except TimeoutError:
            out["without_list"] = f"timeout: {s.timeout:g}s 동안 CNSRREQ 응답 없음"
        await s.list_conditions(label="nolist:then-list")
        r2 = await s.search(seq, label="nolist:after-list", max_pages=1)
        out["after_list_same_connection"] = public(r2)
    return out


async def test_interval(rec: Recorder, profile: str, seqs: list[str], intervals: list[float], per_group: int) -> dict[str, Any]:
    groups = []
    for interval in intervals:
        async with Session(profile, rec, label=f"interval:{interval:g}", drain=0) as s:
            await s.list_conditions(label="interval:list")
            t0 = time.monotonic()
            codes = []
            for i in range(per_group):
                seq = seqs[i % len(seqs)]
                msg, elapsed = await s.request({"trnm": "CNSRREQ", "seq": seq, "search_type": "0", "stex_tp": "K"}, label=f"interval:{interval:g}:{i}", drain=0)
                codes.append(return_code_of(msg))
                if interval:
                    await asyncio.sleep(interval)
            span = round(time.monotonic() - t0, 2)
            limited = [i for i, c in enumerate(codes) if c in RATE_LIMIT_CODES]
            recovery_s = None
            if limited:
                t1 = time.monotonic()
                for _ in range(30):
                    await asyncio.sleep(0.5)
                    msg, _ = await s.request({"trnm": "CNSRREQ", "seq": seqs[0], "search_type": "0", "stex_tp": "K"}, label=f"interval:{interval:g}:recovery", drain=0)
                    if return_code_of(msg) in (None, 0):
                        recovery_s = round(time.monotonic() - t1, 2)
                        break
            group = {"interval_s": interval, "requests": per_group, "span_s": span, "rate_limited_indexes": limited, "codes": dict(Counter(str(c) for c in codes)), "recovery_s": recovery_s, "bare_messages": s.bare_count}
            groups.append(group)
            print(f"  interval={interval:g}s span={span}s limited={limited} recovery={recovery_s}", flush=True)
        await asyncio.sleep(3)
    return {"per_group": per_group, "groups": groups}


async def test_repeat(rec: Recorder, profile: str, seq: str, offsets: list[float]) -> dict[str, Any]:
    runs = []
    async with Session(profile, rec, label="repeat", drain=1.0) as s:
        await s.list_conditions(label="repeat:list")
        base = time.monotonic()
        baseline = None
        for offset in offsets:
            wait = offset - (time.monotonic() - base)
            if wait > 0:
                await asyncio.sleep(wait)
            r = await s.search(seq, label=f"repeat:+{offset:g}s")
            codes = set(r["codes"])
            if baseline is None and r["error"] is None:
                baseline = codes
            runs.append({"offset_s": offset, "error": r["error"], "row_count": r["row_count"], "same_as_first": codes == baseline if baseline is not None and r["error"] is None else None, "elapsed_ms": r["elapsed_ms"]})
            print(f"  repeat +{offset:g}s: rows={r['row_count']} err={r['error']}", flush=True)
        bare = s.bare_count
    return {"seq": seq, "runs": runs, "bare_messages": bare}


async def test_exchange(rec: Recorder, profile: str, seq: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    async with Session(profile, rec, label="stex") as s:
        await s.list_conditions(label="stex:list")
        for stex in ("K", "N", "A"):
            r = await s.search(seq, label=f"stex:{stex}", stex_tp=stex, rate_limit_retries=2)
            out[stex] = {"error": r["error"], "row_count": r["row_count"], "codes": r["codes"]}
            await asyncio.sleep(0.5)
    if not out["K"]["error"] and not out["A"]["error"]:
        k, a = set(out["K"]["codes"]), set(out["A"]["codes"])
        out["K_subset_of_A"] = k <= a
        out["A_minus_K"] = len(a - k)
    for stex in ("K", "N", "A"):
        out[stex].pop("codes")
    return {"seq": seq, **out}


def compare_profiles(sweeps: dict[str, Any]) -> dict[str, Any]:
    names = list(sweeps)
    if len(names) != 2 or not all(sweeps.values()):
        return {"skipped": True}
    a, b = (sweeps[n]["results"] for n in names)
    rows = []
    for seq in sorted(set(a) & set(b), key=lambda x: int(x) if x.isdigit() else x):
        sa, sb = set(a[seq]["codes"]), set(b[seq]["codes"])
        union = sa | sb
        rows.append({"seq": seq, "name_equal": a[seq]["name"] == b[seq]["name"], "counts": [len(sa), len(sb)], "equal": sa == sb, "jaccard": round(len(sa & sb) / len(union), 3) if union else 1.0, "errors": [a[seq]["error"], b[seq]["error"]]})
    return {"profiles": names, "rows": rows, "equal_sets": sum(r["equal"] for r in rows), "total": len(rows)}


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profiles", nargs="+", default=["kiwoom-real-vibe", "kiwoom-demo"])
    parser.add_argument("--out", default=None, help="출력 디렉터리 (기본: scripts/phase0/output/<시각>)")
    parser.add_argument("--delay", type=float, default=0.5, help="sweep 조건식 간 대기(초)")
    parser.add_argument("--quick", action="store_true", help="재조회·간격 테스트를 짧게")
    args = parser.parse_args()

    started = now_kst()
    out_dir = Path(args.out) if args.out else Path(__file__).parent / "output" / started.strftime("%Y%m%d-%H%M%S")
    rec = Recorder(out_dir)
    rec.summary["env"] = {"script_version": SCRIPT_VERSION, "started_at_kst": started.isoformat(), "weekday_kst": started.strftime("%A"), "python": sys.version.split()[0], "system": platform.system(), "profiles": args.profiles}

    print("keyring 잠금 해제와 토큰 확인을 진행합니다.", flush=True)
    modes = {}
    for profile in args.profiles:
        client = get_ws_client(profile=profile)
        client.auth.get_access_token()
        modes[profile] = client.auth.mode
    rec.summary["env"]["modes"] = modes
    print(f"프로필 모드: {modes}", flush=True)

    sweeps = {}
    for profile in args.profiles:
        sweeps[profile] = await guarded(rec, f"sweep[{profile}]", test_sweep(rec, profile, args.delay))
    rec.summary["profile_compare"] = compare_profiles(sweeps)

    primary = args.profiles[0]
    primary_sweep = sweeps.get(primary)
    if primary_sweep:
        results = primary_sweep["results"]
        ok = {s: r for s, r in results.items() if not r["error"]}
        largest = max(ok, key=lambda s: ok[s]["row_count"]) if ok else "0"
        rec.summary["picked"] = {"largest_seq": largest, "paginated_seqs": [s for s, r in ok.items() if r["page_count"] > 1]}
        await guarded(rec, "without_list", test_without_list(rec, primary, largest))
        offsets = [0, 1, 5] if args.quick else [0, 1, 5, 15, 30]
        await guarded(rec, "repeat", test_repeat(rec, primary, largest, offsets))
        intervals = [0.0, 0.25] if args.quick else [0.0, 0.1, 0.25, 0.5]
        await guarded(rec, "interval", test_interval(rec, primary, list(results)[:10], intervals, per_group=10))
        await guarded(rec, "exchange", test_exchange(rec, primary, largest))

    rec.summary["env"]["finished_at_kst"] = now_kst().isoformat()
    rec.close()
    print(f"\n완료. 결과: {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
