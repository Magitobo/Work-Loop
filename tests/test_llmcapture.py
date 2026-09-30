import base64
import json
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from workloop import llmcapture  # noqa: E402

NOW = datetime(2026, 9, 30, 1, 0, 0, tzinfo=timezone.utc)


def _b64(obj) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj)
    return base64.b64encode(s.encode()).decode()


def _metric(mid, minutes, inp, out, cache=0):
    return {"id": mid, "timestamp": (NOW + timedelta(minutes=minutes)).isoformat(), "model": "mlx/Qwen",
            "duration_ms": 1000, "has_capture": True,
            "tokens": {"input_tokens": inp, "output_tokens": out, "cache_tokens": cache}}


def _step(inp, out, cache_read=0):
    return json.dumps({"type": "step_finish",
                       "part": {"tokens": {"input": inp, "output": out, "cache": {"read": cache_read, "write": 0}}}})


SSE = (
    'data: {"choices":[{"delta":{"reasoning":"Let me "}}]}\n\n'
    'data: {"choices":[{"delta":{"reasoning":"think."}}]}\n\n'
    'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"bash","arguments":"{\\"cmd\\":"}}]}}]}\n\n'
    'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"ls\\"}"}}]}}]}\n\n'
    'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
    'data: [DONE]\n\n'
)


class TestParseResponse(unittest.TestCase):
    def test_sse_stream_reassembled(self):
        r = llmcapture._parse_response(SSE)
        self.assertEqual(r["reasoning"], "Let me think.")
        self.assertEqual(r["tool_calls"], [{"name": "bash", "arguments": '{"cmd":"ls"}'}])
        self.assertEqual(r["finish_reason"], "tool_calls")

    def test_plain_json_response(self):
        body = json.dumps({"choices": [{"finish_reason": "stop",
                                        "message": {"content": "Hi", "reasoning": "greet"}}]})
        r = llmcapture._parse_response(body)
        self.assertEqual((r["content"], r["reasoning"], r["finish_reason"]), ("Hi", "greet", "stop"))


class TestCollect(unittest.TestCase):
    def _run(self, metrics, captures, steps):
        tmp = tempfile.mkdtemp()
        log = Path(tmp) / "2026-09-30_01-00-00_Item.log"
        log.write_text("\n".join(steps) + "\n")

        def fake_get(url):
            if url.endswith("/api/metrics"):
                return metrics
            return captures[int(url.rsplit("/", 1)[1])]

        with unittest.mock.patch.object(llmcapture, "_get_json", side_effect=fake_get):
            out = llmcapture.collect("http://studio:5800/", log, NOW, NOW + timedelta(minutes=10))
        return out, [json.loads(l) for l in out.read_text().splitlines()]

    def test_keeps_only_session_requests_and_marks_prefix(self):
        msgs1 = [{"role": "user", "content": "a"}]
        msgs2 = msgs1 + [{"role": "assistant", "content": "b"}]
        msgs3 = [{"role": "user", "content": "CHANGED"}] + msgs2[1:]
        req = lambda m: {"messages": m, "temperature": 0.7, "presence_penalty": 1.5}
        resp = {"choices": [{"message": {"content": "x"}}]}
        metrics = [
            _metric(0, 1, 100, 10),
            _metric(1, 2, 20, 11, cache=100),   # prompt = 120 via cache
            _metric(2, 3, 130, 12),
            _metric(3, 4, 999, 99),             # another session, same window
            _metric(4, 60, 100, 10),            # outside window
        ]
        caps = {i: {"req_body": _b64(req(m)), "resp_body": _b64(resp)}
                for i, m in enumerate([msgs1, msgs2, msgs3])}
        out, rows = self._run(metrics, caps, [_step(100, 10), _step(20, 11, 100), _step(130, 12)])
        self.assertEqual(out.name, "2026-09-30_01-00-00_Item.llm.jsonl")
        header, reqs = rows[0], rows[1:]
        self.assertEqual((header["requests_in_window"], header["matched"], header["captured"]), (4, 3, 3))
        self.assertEqual([r["id"] for r in reqs], [0, 1, 2])
        self.assertEqual(reqs[0]["params"], {"temperature": 0.7, "presence_penalty": 1.5})
        self.assertNotIn("messages", reqs[0])
        self.assertIsNone(reqs[0]["prefix_match_chars"])
        self.assertEqual(reqs[1]["prefix_match_chars"], reqs[0]["prompt_chars"])   # append-only
        self.assertLess(reqs[2]["prefix_match_chars"], reqs[1]["prompt_chars"])    # prompt changed

    def test_request_without_capture_kept_with_metrics_only(self):
        m = _metric(0, 1, 100, 10)
        m["has_capture"] = False
        _, rows = self._run([m], {}, [_step(100, 10)])
        self.assertFalse(rows[1]["captured"])
        self.assertEqual(rows[1]["tokens"]["output_tokens"], 10)

    def test_server_unreachable_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "x.log"
            log.write_text("")
            with unittest.mock.patch.object(llmcapture, "_get_json", side_effect=OSError("down")):
                self.assertIsNone(llmcapture.collect("http://studio:5800", log, NOW, NOW))
            self.assertFalse(llmcapture.capture_path(log).exists())


if __name__ == "__main__":
    unittest.main()
