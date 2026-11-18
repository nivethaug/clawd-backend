"""DreamStudio World guide: a light, tool-free LLM chat for the explore-world robot.

POST /api/guide/chat  {message, history?, where?}  ->  {reply, action}
- No auth (public demo) but rate limited per IP and token capped.
- Key stays server side: z.ai coding endpoint first, OpenRouter fallback.
"""
import json
import logging
import os
import re
import threading
import time
from collections import defaultdict, deque
from typing import List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

logger = logging.getLogger("api.guide_router")
router = APIRouter()

ACTIONS = ["none", "walk_plaza", "walk_building", "walk_waterfall", "walk_river", "floor_0", "floor_1", "floor_2", "floor_3", "floor_4", "wave", "nod", "shake", "fly"]

SYSTEM = (
    "You are the robot guide inside DreamAgent's DreamStudio world, a 3D mountain scene. "
    "DreamAgent (dreamagent.cloud): users describe an idea in chat and AI builds and deploys real products "
    "(websites, apps, dashboards, Telegram and Discord bots, scheduled agents). Every project gets a "
    "<name>.dreamagent.cloud address; custom domains on Pro and above. Every build is checked after it is built. "
    "Edit by chat, full source, version history, GitHub export. Plans: Free, Pro, Dream, Enterprise. "
    "Superpowers: song, AI video, music video, TTS, image generation, voice clone (paid credits); "
    "free tools: transcription, FFmpeg, image processing, PDF tools, slideshows. "
    "Only state facts listed here; if unsure, say you are not sure and suggest dreamagent.cloud. "
    "Never invent prices. "
    "Places you can walk to: plaza (blue light ring), building (the dream factory), waterfall, river. "
    "The dream factory has a glass lift and floors: lobby (floor_0), floor 1 websites (floor_1), floor 2 agents (floor_2), floor 3 bots (floor_3), floor 4 superpowers (floor_4). "
    "Use floor_N when the visitor asks to go to or see that floor. "
    "Reply with ONLY compact JSON: {\"reply\": \"<=2 short friendly spoken sentences\", \"action\": \"<one of "
    + ", ".join(ACTIONS)
    + ">\"}. Use a walk_* action only if the visitor asks to go or see something; wave to greet; nod for yes; shake for no."
)

_hits = defaultdict(deque)
_lock = threading.Lock()
LIMIT, WINDOW = 12, 60  # requests per IP per minute


def _allow(ip: str) -> bool:
    now = time.time()
    with _lock:
        q = _hits[ip]
        while q and now - q[0] > WINDOW:
            q.popleft()
        if len(q) >= LIMIT:
            return False
        q.append(now)
        if len(_hits) > 5000:
            for k in [k for k, v in _hits.items() if not v][:1000]:
                _hits.pop(k, None)
        return True


class Turn(BaseModel):
    role: str
    content: str = Field(max_length=500)


class GuideReq(BaseModel):
    message: str = Field(min_length=1, max_length=400)
    history: List[Turn] = []
    where: Optional[str] = Field(default=None, max_length=60)


def _llm(messages) -> str:
    zai = os.getenv("ZAI_API_KEY", "").strip()
    orr = os.getenv("OPENROUTER_API_KEY", "").strip()
    tries = []
    if zai and os.getenv("GUIDE_USE_ZAI") == "1":  # z.ai key is 401 on main for now; OpenRouter only
        tries.append(("https://api.z.ai/api/coding/paas/v4/chat/completions", zai, "glm-5.3-flash"))
    if orr:
        tries.append(("https://openrouter.ai/api/v1/chat/completions", orr, os.getenv("OPENROUTER_MODEL", "z-ai/glm-5.3-flash")))
    last = None
    for url, key, model in tries:
        try:
            r = httpx.post(url, json={"model": model, "max_tokens": 220, "temperature": 0.7, "messages": messages},
                           headers={"Authorization": f"Bearer {key}"}, timeout=25)
            r.raise_for_status()
            return (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        except Exception as e:  # quota (429) or network: try the next tier
            last = e
            logger.warning("guide llm tier failed: %s", e)
    raise RuntimeError(f"no LLM available: {last}")


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            reply = str(d.get("reply", "")).strip()
            act = d.get("action", "none")
            if reply:
                return {"reply": reply[:400], "action": act if act in ACTIONS else "none"}
        except Exception:
            pass
    return {"reply": (text or "Sorry, I lost my words for a second.").strip()[:400], "action": "none"}


@router.post("/chat")
async def guide_chat(req: GuideReq, request: Request):
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
    if not _allow(ip):
        raise HTTPException(status_code=429, detail="Slow down a little, I am still catching up.")
    msgs = [{"role": "system", "content": SYSTEM + (f" The visitor is currently near: {req.where}." if req.where else "")}]
    for t in req.history[-6:]:
        if t.role in ("user", "assistant"):
            msgs.append({"role": t.role, "content": t.content})
    msgs.append({"role": "user", "content": req.message})
    try:
        text = await run_in_threadpool(_llm, msgs)
    except Exception as e:
        logger.error("guide chat failed: %s", e)
        raise HTTPException(status_code=503, detail="The guide is resting. Try again in a moment.")
    return _parse(text)


class TtsReq(BaseModel):
    text: str = Field(min_length=1, max_length=400)


_tts_hits = defaultdict(deque)


@router.post("/tts")
async def guide_tts(req: TtsReq, request: Request):
    """Robot guide voice: proxies the local Piper service (guide-tts, 127.0.0.1:8005). Rate limited per IP."""
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
    now = time.time()
    with _lock:
        q = _tts_hits[ip]
        while q and now - q[0] > WINDOW:
            q.popleft()
        if len(q) >= 20:
            raise HTTPException(status_code=429, detail="Too many voice requests, slow down a little.")
        q.append(now)

    def _call():
        r = httpx.post("http://127.0.0.1:8005/tts", json={"text": req.text}, timeout=20)
        r.raise_for_status()
        return r.content

    try:
        wav = await run_in_threadpool(_call)
    except Exception as e:
        logger.warning("guide tts failed: %s", e)
        raise HTTPException(status_code=503, detail="voice unavailable")
    return Response(content=wav, media_type="audio/wav")
