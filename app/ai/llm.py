"""Talks to the language model. One internal message format (Anthropic-style blocks) and two wire formats:

  * Anthropic Messages API (Claude)
  * OpenAI-compatible chat completions (OpenAI, Ollama and many others)

stream(...) yields plain dict events:
  {"type": "text", "delta": "..."}                        words as they arrive
  {"type": "tool_use", "id", "name", "input"}              a finished tool call
  {"type": "stop", "reason": "end_turn|tool_use|max_tokens", "usage": {...}}
Only the standard library is used for the network, so nothing extra has to be installed."""
from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.request
from typing import Iterator

from app.ai import store


log = logging.getLogger("fathom")

class LLMError(Exception):
    pass


def _friendly(code: int, body: str, provider: str) -> str:
    msg = body
    try:
        j = json.loads(body)
        msg = (j.get("error") or {}).get("message") or j.get("message") or j.get("detail") or body
        if isinstance(msg, dict):
            msg = json.dumps(msg)
    except Exception:
        pass
    msg = str(msg)[:600]
    if code in (401, 403):
        return f"The {provider} key was not accepted ({code}). Open the Assistant settings and check the key. {msg}"
    if code == 404:
        return f"The model or address was not found ({msg}). Check the model name in the Assistant settings."
    if code == 429:
        return f"Too many requests or the account is out of credit right now ({msg})."
    if code in (500, 502, 503, 529):
        return f"The {provider} service is busy or down ({code}). {msg}"
    return f"{provider} said: {msg} ({code})"


def _ollama_self_heal() -> bool:
    """Ollama says 'not found' for a model whose files are on disk: Windows may be refusing Ollama's link files. Replace them by copies."""
    try:
        from app import ollama_fix
        return ollama_fix.repair_links() > 0
    except Exception:
        return False


def _open(url: str, headers: dict, body: dict, timeout: int, provider: str, cancel=None):
    data = json.dumps(body).encode("utf-8")
    last = None
    is_ollama = provider.lower() == "ollama"
    for attempt in range(4):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503, 529) and attempt < 3:
                try:
                    wait = float(e.headers.get("retry-after") or 0)
                except (TypeError, ValueError):
                    wait = 0
                last = _friendly(e.code, text, provider)
                time.sleep(min(20, wait or 2 * (attempt + 1)))
                if cancel is not None and cancel.is_set():
                    raise LLMError("Stopped.")
                continue
            if is_ollama and e.code == 404 and attempt == 0 and _ollama_self_heal():
                continue
            if is_ollama and e.code == 404:
                raise LLMError("Ollama cannot open the model. Close this and double-click Fix-Ollama.cmd in the Fathom folder (it repairs Ollama), "
                               "or choose an online AI in Assistant > Settings. (" + _friendly(e.code, text, provider) + ")")
            raise LLMError(_friendly(e.code, text, provider))
        except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
            reason = getattr(e, "reason", e)
            if is_ollama and attempt == 0:
                try:
                    from app import ollama_keep
                    if ollama_keep.ensure_running(60):
                        continue
                except Exception:
                    log.debug("could not start Ollama", exc_info=True)
            if is_ollama:
                try:
                    from app import ollama_keep
                    missing = not ollama_keep._exe()
                except Exception:
                    missing = False
                if missing:
                    raise LLMError("The free assistant (Ollama) is not installed on this PC. That is normal for the Lite edition. To add it, run Fathom.bat full "
                                   "(or run Fathom-Setup.vbs and tick the assistant), or open Assistant > Settings and pick an online AI (Claude, OpenAI and others) with your own key.")
                raise LLMError(f"Could not reach Ollama at {url.split('/v1')[0]} ({reason}). Is Ollama running? Install it from ollama.com, then run: ollama pull {store.DEFAULTS['models']['ollama']}")
            raise LLMError(f"Could not reach {provider} ({reason}). Are you online?")
    raise LLMError(last or "The service did not answer.")


def _sse(resp, cancel=None) -> Iterator[tuple[str, dict]]:
    """server-sent events -> (event name, json)"""
    event = ""
    for raw in resp:
        if cancel is not None and cancel.is_set():
            resp.close()
            raise LLMError("Stopped.")
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            event = ""
            continue
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            d = line[5:].strip()
            if d == "[DONE]":
                return
            try:
                yield event, json.loads(d)
            except json.JSONDecodeError:
                continue


# ================================================================== Anthropic
def _anthropic_messages(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        out.append({"role": m["role"], "content": content})
    return out


def stream_anthropic(cfg: dict, system: str, messages: list[dict], tools: list[dict], max_tokens: int, cancel) -> Iterator[dict]:
    key = store.get_secret("anthropic")
    if not key:
        raise LLMError("No Anthropic key yet. Open the Assistant settings and paste your key (from console.anthropic.com), or choose a free local model (Ollama).")
    base = (cfg["base_urls"].get("anthropic") or "https://api.anthropic.com").rstrip("/")
    body = {"model": cfg["models"]["anthropic"], "max_tokens": max_tokens, "stream": True, "messages": _anthropic_messages(messages),
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]}
    if tools:
        ts = [{"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]} for t in tools]
        ts[-1]["cache_control"] = {"type": "ephemeral"}
        body["tools"] = ts
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json", "accept": "text/event-stream"}
    resp = _open(base + "/v1/messages", headers, body, 600, "Anthropic", cancel)
    blocks: dict[int, dict] = {}
    usage: dict = {}
    reason = "end_turn"
    try:
        for ev, d in _sse(resp, cancel):
            t = d.get("type") or ev
            if t == "message_start":
                usage.update((d.get("message") or {}).get("usage") or {})
            elif t == "content_block_start":
                cb = d.get("content_block") or {}
                blocks[d["index"]] = {"type": cb.get("type"), "id": cb.get("id"), "name": cb.get("name"), "json": "", "text": cb.get("text", "")}
            elif t == "content_block_delta":
                dl = d.get("delta") or {}
                b = blocks.get(d["index"])
                if dl.get("type") == "text_delta" and dl.get("text"):
                    yield {"type": "text", "delta": dl["text"]}
                elif dl.get("type") == "input_json_delta" and b is not None:
                    b["json"] += dl.get("partial_json", "")
            elif t == "content_block_stop":
                b = blocks.get(d["index"])
                if b and b["type"] == "tool_use":
                    try:
                        inp = json.loads(b["json"]) if b["json"].strip() else {}
                    except json.JSONDecodeError:
                        inp = {"_error": "the tool call was cut off"}
                    yield {"type": "tool_use", "id": b["id"], "name": b["name"], "input": inp}
            elif t == "message_delta":
                reason = (d.get("delta") or {}).get("stop_reason") or reason
                usage.update(d.get("usage") or {})
            elif t == "error":
                raise LLMError(((d.get("error") or {}).get("message")) or "The service reported an error.")
    finally:
        try:
            resp.close()
        except Exception:
            pass
    yield {"type": "stop", "reason": reason, "usage": usage}


# ================================================================== OpenAI-compatible
def _openai_messages(system: str, messages: list[dict]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
            continue
        if m["role"] == "assistant":
            text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            calls = [{"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})}} for b in content if b.get("type") == "tool_use"]
            msg: dict = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
            continue
        parts, pending_images = [], []
        for b in content:
            if b.get("type") == "tool_result":
                inner = b.get("content")
                text = inner if isinstance(inner, str) else "\n".join(x.get("text", "") for x in (inner or []) if x.get("type") == "text")
                imgs = [] if isinstance(inner, str) else [x for x in (inner or []) if x.get("type") == "image"]
                out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": text or ("(done)" if not imgs else "(picture follows)")})
                pending_images += imgs
            elif b.get("type") == "text":
                parts.append({"type": "text", "text": b["text"]})
            elif b.get("type") == "image":
                parts.append({"type": "image_url", "image_url": {"url": f"data:{b['source']['media_type']};base64,{b['source']['data']}"}})
        for im in pending_images:
            parts.append({"type": "image_url", "image_url": {"url": f"data:{im['source']['media_type']};base64,{im['source']['data']}"}})
        if parts:
            out.append({"role": "user", "content": parts})
    return out


def _ollama_pick(base: str, wanted: str) -> str:
    """If Ollama does not list the chosen model but lists another one, use that one instead of failing with 'not found'."""
    try:
        root = base[:-3] if base.endswith("/v1") else base
        with urllib.request.urlopen(root + "/api/tags", timeout=3) as r:
            names = [m.get("name", "") for m in json.loads(r.read().decode("utf-8", "replace")).get("models", [])]
    except Exception:
        return wanted
    if not names or wanted in names or (":" not in wanted and wanted + ":latest" in names):
        return wanted
    for pref in ("qwen3-vl:4b-instruct", "qwen3-vl", "qwen2.5vl", "gemma3", "llava", "qwen3", "llama3", "qwen2.5"):
        for n in names:
            if n.startswith(pref):
                return n
    return names[0]


def warm_up_ollama(cfg: dict | None = None) -> None:
    """Load the local model into the graphics card now (and keep it there), so the first answer does not wait for it."""
    try:
        cfg = cfg or store.load()
        if cfg.get("provider") != "ollama":
            return
        base = (cfg["base_urls"].get("ollama") or "").rstrip("/")
        root = base[:-3] if base.endswith("/v1") else base
        model = _ollama_pick(base, cfg["models"]["ollama"])
        req = urllib.request.Request(root + "/api/generate", data=json.dumps({"model": model, "keep_alive": "60m"}).encode("utf-8"),
                                     headers={"content-type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=600).read()
    except Exception:
        return
    _warm_prompt_prefix(cfg, base, model)


def _warm_prompt_prefix(cfg: dict, base: str, model: str) -> None:
    """Fathom's instructions and tool list are about 6000 tokens and are the same in every message. Ollama keeps what it has already read
    of them while the model stays loaded, so reading them once now (one token of answer) makes the first real question start right away
    instead of waiting minutes on a modest graphics card. The answer is thrown away; nothing is saved and no tool runs."""
    try:
        from app.ai import agent, tools
        system = agent.system_prompt(None)
        body = {"model": model, "messages": _openai_messages(system, [{"role": "user", "content": "hi"}]), "stream": False, "max_tokens": 1,
                "tools": [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in tools.schemas()]}
        req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                                     headers={"content-type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=900).read()
    except Exception:
        log.debug("prompt warm-up skipped", exc_info=True)


def stream_openai(cfg: dict, provider: str, system: str, messages: list[dict], tools: list[dict], max_tokens: int, cancel) -> Iterator[dict]:
    key = store.get_secret(provider)
    if provider == "openai" and not key:
        raise LLMError("No OpenAI key yet. Open the Assistant settings and paste your key, or choose Claude or a free local model (Ollama).")
    base = (cfg["base_urls"].get(provider) or "").rstrip("/")
    model = cfg["models"][provider]
    if provider == "ollama":
        model = _ollama_pick(base, model)
    body = {"model": model, "messages": _openai_messages(system, messages), "stream": True, "max_tokens": max_tokens}
    if tools:
        body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in tools]
    headers = {"content-type": "application/json", "accept": "text/event-stream"}
    if key:
        headers["authorization"] = "Bearer " + key
    resp = _open(base + "/chat/completions", headers, body, 600, "Ollama" if provider == "ollama" else "OpenAI", cancel)
    calls: dict[int, dict] = {}
    reason, usage = "end_turn", {}
    try:
        for _ev, d in _sse(resp, cancel):
            if d.get("usage"):
                usage = {"input_tokens": d["usage"].get("prompt_tokens"), "output_tokens": d["usage"].get("completion_tokens")}
            for ch in d.get("choices") or []:
                dl = ch.get("delta") or {}
                if dl.get("content"):
                    yield {"type": "text", "delta": dl["content"]}
                for tc in dl.get("tool_calls") or []:
                    c = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "args": ""})
                    c["id"] = tc.get("id") or c["id"]
                    f = tc.get("function") or {}
                    c["name"] = f.get("name") or c["name"]
                    c["args"] += f.get("arguments") or ""
                if ch.get("finish_reason"):
                    reason = {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens"}.get(ch["finish_reason"], ch["finish_reason"])
    finally:
        try:
            resp.close()
        except Exception:
            pass
    for i in sorted(calls):
        c = calls[i]
        try:
            inp = json.loads(c["args"]) if c["args"].strip() else {}
        except json.JSONDecodeError:
            inp = {"_error": "the tool call was cut off"}
        yield {"type": "tool_use", "id": c["id"] or f"call_{i}_{int(time.time())}", "name": c["name"], "input": inp}
    if calls:
        reason = "tool_use"
    yield {"type": "stop", "reason": reason, "usage": usage}


def stream(system: str, messages: list[dict], tools: list[dict], cancel, max_tokens: int = 16000, cfg: dict | None = None) -> Iterator[dict]:
    cfg = cfg or store.load()
    p = cfg["provider"]
    if p == "anthropic":
        return stream_anthropic(cfg, system, messages, tools, max_tokens, cancel)
    if p in ("openai", "ollama"):
        return stream_openai(cfg, p, system, messages, tools, min(max_tokens, 8192) if p == "ollama" else max_tokens, cancel)
    raise LLMError("Choose a model provider in the Assistant settings.")


def complete(system: str, messages: list[dict], cancel=None, max_tokens: int = 4000, cfg: dict | None = None) -> str:
    """one non-interactive answer (used for things like reading handwriting from a picture)"""
    import threading
    text = []
    for ev in stream(system, messages, [], cancel or threading.Event(), max_tokens, cfg):
        if ev["type"] == "text":
            text.append(ev["delta"])
    return "".join(text)


def test_connection() -> dict:
    import threading
    try:
        t = complete("Reply with exactly: ready", [{"role": "user", "content": "Say ready."}], threading.Event(), 20)
        return {"ok": True, "reply": t.strip()[:80]}
    except LLMError as e:
        return {"ok": False, "error": str(e)}
