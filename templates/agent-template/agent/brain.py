"""
DreamAgent Agent Brain — LLM-powered decision engine for agent projects.

Receives trigger events (Telegram, webhook, schedule) and uses the
configured LLM (typesafe/jev-router via OpenRouter) to reason about
what to do. Executes tools, sends deliveries, maintains state.

Called from executor.py when a job has use_ai=true or task_type=brain.

Env vars required (in project .env):
    OPENROUTER_API_KEY  — key for the LLM (from Global Integrations or manual)
    AGENT_MODEL         — default: typesafe/jev-router
    DREAMAGENT_TOOLS_URL — platform tools-api base URL
    DREAMAGENT_PROJECT_SECRET — project secret for tools-api auth
    PROJECT_ID          — this project's ID
"""

import json
import os
import urllib.request

MAX_TURNS = 6
DEFAULT_MODEL = "typesafe/jev-router"


# Provider registry — configured at creation time via project .env
# AGENT_PROVIDER: openrouter | openai | anthropic | zai
# AGENT_MODEL: model slug (e.g. typesafe/jev-router, gpt-4o-mini)
_PROVIDERS = {
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key_env": "OPENROUTER_API_KEY",
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "key_env": "OPENAI_API_KEY",
    },
    "anthropic": {
        "url": "https://api.anthropic.com/v1/messages",
        "key_env": "ANTHROPIC_API_KEY",
    },
    "zai": {
        "url": "https://api.z.ai/api/paas/v4/chat/completions",
        "key_env": "ZAI_API_KEY",
    },
}


def _llm(messages):
    provider = os.getenv("AGENT_PROVIDER", "openrouter").lower()
    model = os.getenv("AGENT_MODEL", DEFAULT_MODEL)
    cfg = _PROVIDERS.get(provider, _PROVIDERS["openrouter"])
    key = os.getenv(cfg["key_env"])
    if not key:
        raise RuntimeError(
            f"Brain not configured. {cfg['key_env']} not set. "
            f"Connect the {provider} integration in Settings, or ask in chat "
            f"to change the brain model.")
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 2000,
    }).encode()
    req = urllib.request.Request(
        cfg["url"], data=payload, method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.loads(r.read().decode())
    # OpenAI-compatible response
    if "choices" in body:
        return body["choices"][0]["message"]["content"]
    # Anthropic response format
    if "content" in body:
        return body["content"][0]["text"] if body["content"] else ""
    raise RuntimeError(f"Unexpected LLM response format from {provider}")


def _system_prompt(trigger_desc: str) -> str:
    tools_url = os.getenv("DREAMAGENT_TOOLS_URL", "")
    project_id = os.getenv("PROJECT_ID", "")
    channels = []
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        channels.append("Telegram (send via sendMessage API)")
    if os.getenv("DISCORD_WEBHOOK_URL"):
        channels.append("Discord (send via webhook)")
    if os.getenv("EMAIL_TO"):
        channels.append("Email (return email intent)")
    oauth = [k.replace("_ACCESS_TOKEN", "").lower() for k in os.environ
             if k.endswith("_ACCESS_TOKEN")]
    return f"""You are DreamAgent — an autonomous AI agent that processes triggers and takes action.

## Trigger Event
{trigger_desc}

## Available Tools
1. fetch_json(url, method?, headers?, body?) — HTTP request
2. proxy_call(provider, method, endpoint, body?, params?) — OAuth call (providers: {', '.join(oauth) or 'none connected'})
3. superpowers_execute(tool, params) — run a superpower tool:
   song(prompt, vocals?), image-gen(prompt, size?), video-gen(prompt),
   voiceover(text, language?), lip-sync(image, audio), whisper(file),
   sharp(file, op), pdf(op, ...), remotion(images, text?)
   → call POST {tools_url}/tools/projects/{project_id}/tools/{{tool}}/execute
     headers: X-Project-Secret: {os.getenv("DREAMAGENT_PROJECT_SECRET", "<from .env>")}
4. state_get(key) / state_set(key, value) — persistent memory
5. send_telegram(message, attach_path?) — send message/file to Telegram
6. send_discord(message) — send via Discord webhook
7. wait — do nothing this run (wait for next trigger)

## Delivery Channels
{', '.join(channels) if channels else 'None configured'}

## Rules
1. Reason step by step about what the trigger requires
2. Use tools to accomplish the task
3. Deliver results via the available channels
4. Return a JSON object with your actions and reply
5. If nothing needs to be done, return empty actions with a reply

Respond with JSON only:
{{"thinking": "...", "actions": [{{"tool": "...", "params": {{...}}}}], "reply": "..."}}"""


def _parse_response(text: str) -> dict:
    """Extract JSON from LLM response (handles markdown wrapping)."""
    content = text
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "{" in content:
        start = content.index("{")
        end = content.rindex("}") + 1
        content = content[start:end]
    return json.loads(content)


def _execute_tool(tool: str, params: dict) -> dict:
    """Execute a tool call. Returns result dict for the LLM."""
    try:
        from services import api_client
    except ImportError:
        return {"error": "api_client not available"}

    if tool == "fetch_json":
        return {"data": api_client.fetch_json(params["url"])}
    elif tool == "proxy_call":
        return {"data": api_client.proxy_call(
            params["provider"], params.get("method", "GET"),
            params["endpoint"], body=params.get("body"),
            params=params.get("params"))}
    elif tool == "superpowers_execute":
        import urllib.request
        url = (os.getenv("DREAMAGENT_TOOLS_URL", "").rstrip("/")
               + f"/tools/projects/{os.getenv('PROJECT_ID')}"
               + f"/tools/{params['tool']}/execute")
        req = urllib.request.Request(url, method="POST",
            data=json.dumps({"op": params.get("op", "generate"),
                             "params": params.get("params", {})}).encode(),
            headers={"X-Project-Secret": os.getenv("DREAMAGENT_PROJECT_SECRET", ""),
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    elif tool == "state_get":
        return {"data": api_client.state_get(params["key"])}
    elif tool == "state_set":
        api_client.state_set(params["key"], params["value"])
        return {"data": "saved"}
    else:
        return {"error": f"Unknown tool: {tool}"}


def _send_telegram(message: str, attach_path: str = None):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    import urllib.request
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": message}).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15)
    if attach_path and os.path.isfile(attach_path):
        url2 = f"https://api.telegram.org/bot{token}/sendDocument"
        boundary = "----DABoundary"
        with open(attach_path, "rb") as f:
            file_data = f.read()
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="document"; '
            f'filename="{os.path.basename(attach_path)}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()
        req2 = urllib.request.Request(url2, data=body, headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}"})
        urllib.request.urlopen(req2, timeout=60)


def _send_discord(message: str):
    webhook = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook:
        return
    import urllib.request
    data = json.dumps({"content": message}).encode()
    req = urllib.request.Request(webhook, data=data,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15)


def run_agent(trigger_data, context=None) -> dict:
    """Run the agent decision loop on a trigger event.

    Args:
        trigger_data: dict or str — the event payload
        context: optional dict with description, capabilities, etc.

    Returns:
        {"actions_executed": [...], "reply": str}
    """
    ctx = context or {}
    trigger_desc = (json.dumps(trigger_data, default=str)[:3000]
                    if isinstance(trigger_data, dict) else str(trigger_data)[:3000])

    messages = [{"role": "system", "content": _system_prompt(trigger_desc)},
                {"role": "user", "content": f"Trigger: {trigger_desc}"}]

    executed = []

    for turn in range(MAX_TURNS):
        response = _llm(messages)
        messages.append({"role": "assistant", "content": response})

        try:
            parsed = _parse_response(response)
        except Exception:
            break  # not JSON — done thinking

        actions = parsed.get("actions", [])
        if not actions:
            break

        tool_results = []
        for action in actions:
            tool = action.get("tool", "")
            params = action.get("params", {})

            if tool == "send_telegram":
                _send_telegram(params.get("message", ""),
                               params.get("attach_path"))
                executed.append({"tool": tool, "status": "sent"})
                tool_results.append({"tool": tool, "result": "sent"})
            elif tool == "send_discord":
                _send_discord(params.get("message", ""))
                executed.append({"tool": tool, "status": "sent"})
                tool_results.append({"tool": tool, "result": "sent"})
            else:
                result = _execute_tool(tool, params)
                executed.append({"tool": tool, "params": params, "result": result})
                tool_results.append({"tool": tool, "result": result})

        messages.append({"role": "user", "content":
                         f"Tool results:\n{json.dumps(tool_results, default=str)[:3000]}\n\n"
                         "Continue or provide your final JSON response."})

    # Extract reply from last assistant message
    reply = ""
    for msg in reversed(messages):
        if msg["role"] == "assistant":
            try:
                parsed = _parse_response(msg["content"])
                reply = parsed.get("reply", "")
            except Exception:
                reply = msg["content"][:200]
            break

    return {"actions_executed": executed, "reply": reply}
