#!/usr/bin/env python3
"""
DreamPilot Deployment Tester

A CLI tool to test DreamPilot project creation and full pipeline deployment.
Used for manual testing, agent-based automation, and CI/CD validation.

Usage:
    dreamtest create --name "Test App" --desc "Pipeline test"
    dreamtest create --name "Agent Test" --desc "Agent run" --agent
    dreamtest create --ci
    dreamtest telegram --name "My Bot" --token "123:abc"
    dreamtest discord --name "My Bot" --token "MTIz.abc.def"
    dreamtest status <project_id>
"""

import argparse
import json
import socket
import subprocess
import sys
import time
from datetime import datetime
from typing import Dict, Optional, Tuple

import requests

# Configuration
API_BASE_URL = "http://localhost:8002"
DEFAULT_TIMEOUT = 600  # 10 minutes
POLL_INTERVAL = 5  # seconds

# Status progression order
STATUS_ORDER = [
    "creating",
    "initializing", 
    "ai_provisioning",
    "building",
    "deploying",
    "verifying",
    "ready",
    "failed"
]

# Phase display names
PHASE_NAMES = {
    "PLANNER": "planner",
    "SCAFFOLD": "scaffold",
    "ACPX": "acpx",
    "ROUTER": "router",
    "BUILD": "build",
    "DEPLOY": "deploy"
}


def log(level: str, message: str) -> None:
    """Print formatted log message."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{level}] {message}")


def log_success(message: str) -> None:
    log("SUCCESS", message)


def log_error(message: str) -> None:
    log("ERROR", message)


def log_info(message: str) -> None:
    log("INFO", message)


def log_check(message: str) -> None:
    log("CHECK", message)


def create_project(name: str, description: str = "", type_id: int = 1, bot_token: str = None) -> Optional[Dict]:
    """
    Create a new project via API.
    
    Returns project data including ID and domain.
    """
    log_info(f"Creating project: {name}")
    type_names = {1: "Website", 2: "Telegram Bot", 3: "Discord Bot", 5: "Scheduler"}
    if type_id in type_names:
        log_info(f"Type: {type_names[type_id]}")

    payload = {
        "name": name,
        "description": description,
        "type_id": type_id
    }

    # Add bot_token for bot projects
    if type_id in (2, 3) and bot_token:
        payload["bot_token"] = bot_token
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/projects",
            json=payload,
            timeout=30
        )
        
        if response.status_code == 201:
            project = response.json()
            log_success(f"Project created successfully")
            log_info(f"Project ID: {project['id']}")
            log_info(f"Domain: {project['domain']}")
            if type_id in (2, 3):
                log_info(f"Bot Port: {project.get('bot_port', 'N/A')}")
            return project
        else:
            log_error(f"Failed to create project: {response.status_code}")
            log_error(response.text)
            return None
            
    except requests.RequestException as e:
        log_error(f"API request failed: {e}")
        return None


def get_project(project_id: int) -> Optional[Dict]:
    """Get project details by ID from /projects list."""
    try:
        response = requests.get(
            f"{API_BASE_URL}/projects",
            timeout=10
        )
        
        if response.status_code == 200:
            projects = response.json()
            for project in projects:
                if project.get("id") == project_id:
                    return project
        return None
        
    except requests.RequestException:
        return None


def get_project_status(project_id: int) -> Optional[str]:
    """Get current project status."""
    project = get_project(project_id)
    if project:
        return project.get("status")
    return None


def get_pipeline_status(project_id: int) -> Optional[Dict]:
    """Get detailed pipeline status."""
    project = get_project(project_id)
    if project and "pipeline_status" in project:
        return project.get("pipeline_status")
    return None


def poll_project_status(project_id: int, timeout: int = DEFAULT_TIMEOUT, agent_mode: bool = False) -> Tuple[str, int]:
    """
    Poll project status until ready or failed.
    
    Returns (final_status, elapsed_seconds)
    """
    start_time = time.time()
    last_status = None
    phase_progress = {}
    
    log_info(f"Monitoring pipeline (timeout: {timeout}s)...")
    print()
    
    while True:
        elapsed = int(time.time() - start_time)
        
        if elapsed > timeout:
            log_error(f"Pipeline timeout after {elapsed}s")
            return "timeout", elapsed
        
        project = get_project(project_id)
        if not project:
            log_error("Failed to fetch project status")
            time.sleep(POLL_INTERVAL)
            continue
        
        status = project.get("status")
        pipeline_status = project.get("pipeline_status", {})
        
        # Display phase progress
        if not agent_mode:
            if status != last_status:
                print(f"  Status: {status} ({elapsed}s)")
                last_status = status
            
            # Show phase progress
            for phase_name in PHASE_NAMES.keys():
                phase_key = PHASE_NAMES[phase_name]
                phase_data = pipeline_status.get(phase_key, {})
                phase_status = phase_data.get("status", "pending")
                
                if phase_key not in phase_progress or phase_progress[phase_key] != phase_status:
                    phase_progress[phase_key] = phase_status
                    
                    if phase_status == "completed":
                        print(f"    [{phase_name:10}] ✓ completed")
                    elif phase_status == "running":
                        print(f"    [{phase_name:10}] ⏳ running...")
                    elif phase_status == "failed":
                        error = phase_data.get("error_code", "unknown")
                        print(f"    [{phase_name:10}] ✗ failed ({error})")
        
        # Check terminal states
        if status == "ready":
            print()
            return "ready", elapsed
        elif status == "failed":
            print()
            return "failed", elapsed
        
        time.sleep(POLL_INTERVAL)


def verify_frontend(domain: str) -> bool:
    """Verify frontend is reachable via HTTP."""
    full_domain = f"{domain}.dreambigwithai.com" if "." not in domain else domain
    url = f"http://{full_domain}"
    log_check(f"Verifying frontend: {url}")
    
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            log_success(f"Frontend reachable (HTTP {response.status_code})")
            return True
        else:
            log_error(f"Frontend returned HTTP {response.status_code}")
            return False
    except requests.RequestException as e:
        log_error(f"Frontend unreachable: {e}")
        return False


def verify_backend(domain: str) -> bool:
    """Verify backend health endpoint on -api subdomain."""
    base_domain = domain.split('.')[0] if '.' in domain else domain
    api_domain = f"{base_domain}-api.dreambigwithai.com"
    url = f"http://{api_domain}/health"
    log_check(f"Verifying backend health: {url}")
    
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "ok":
                log_success("Backend health check passed")
                return True
            else:
                log_error(f"Backend returned unexpected status: {data}")
                return False
        else:
            log_error(f"Backend returned HTTP {response.status_code}")
            return False
    except requests.RequestException as e:
        log_error(f"Backend unreachable: {e}")
        return False


def check_dns(domain: str) -> bool:
    """Check DNS resolution."""
    full_domain = f"{domain}.dreambigwithai.com" if "." not in domain else domain
    log_check(f"Verifying DNS resolution: {full_domain}")
    
    try:
        ip = socket.gethostbyname(full_domain)
        log_success(f"Domain resolved to {ip}")
        return True
    except socket.gaierror as e:
        log_error(f"DNS resolution failed: {e}")
        return False


def check_pm2(project_name: str) -> Tuple[bool, bool]:
    """
    Check PM2 processes for frontend and backend.
    
    Returns (frontend_running, backend_running)
    """
    log_check("Checking PM2 processes...")
    
    frontend_running = False
    backend_running = False
    
    try:
        result = subprocess.run(
            ["pm2", "list"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            # Parse PM2 text output (no --json flag available)
            output = result.stdout
            name_lower = project_name.lower().replace(" ", "-")
            
            # Check for frontend and backend in PM2 list
            for line in output.split("\n"):
                line_lower = line.lower()
                if name_lower in line_lower:
                    if "frontend" in line_lower and "online" in line_lower:
                        frontend_running = True
                        log_success(f"Frontend PM2 process running")
                    elif "backend" in line_lower and "online" in line_lower:
                        backend_running = True
                        log_success(f"Backend PM2 process running")
            
            if not frontend_running:
                log_error("Frontend PM2 process not found or not running")
            if not backend_running:
                log_error("Backend PM2 process not found or not running")
        else:
            log_error(f"PM2 list failed: {result.stderr}")
            
    except subprocess.TimeoutExpired:
        log_error("PM2 command timed out")
    except json.JSONDecodeError:
        log_error("Failed to parse PM2 output")
    except FileNotFoundError:
        log_error("PM2 not found - skipping process check")
    
    return frontend_running, backend_running


def verify_telegram_bot(project_id: int, domain: str) -> Tuple[bool, bool, bool]:
    """
    Verify Telegram bot webhook endpoints.
    
    Returns (health_ok, root_ok, pm2_ok)
    """
    log_check(f"Verifying Telegram bot webhook endpoints...")
    
    base_domain = domain.split('.')[0] if '.' in domain else domain
    bot_domain = f"{base_domain}-api.dreambigwithai.com"
    
    health_ok = False
    root_ok = False
    
    # Check health endpoint
    health_url = f"https://{bot_domain}/health"
    log_info(f"Checking health endpoint: {health_url}")
    
    try:
        response = requests.get(health_url, timeout=10, verify=True)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "healthy":
                log_success(f"Health endpoint verified")
                health_ok = True
            else:
                log_error(f"Unexpected health response: {data}")
        else:
            log_error(f"Health endpoint returned {response.status_code}")
    except requests.exceptions.SSLError:
        log_error(f"SSL certificate error for {bot_domain}")
    except Exception as e:
        log_error(f"Health endpoint check failed: {e}")
    
    # Check root endpoint
    root_url = f"https://{bot_domain}/"
    log_info(f"Checking root endpoint: {root_url}")
    
    try:
        response = requests.get(root_url, timeout=10, verify=True)
        if response.status_code == 200:
            data = response.json()
            if "message" in data and "Telegram Bot API" in data.get("message", ""):
                log_success(f"Root endpoint verified")
                root_ok = True
            else:
                log_error(f"Unexpected root response: {data}")
        else:
            log_error(f"Root endpoint returned {response.status_code}")
    except Exception as e:
        log_error(f"Root endpoint check failed: {e}")
    
    # Check PM2 process
    pm2_process_name = f"tg-bot-{project_id}"
    log_info(f"Checking PM2 process: {pm2_process_name}")
    
    pm2_ok = False
    try:
        result = subprocess.run(
            ["pm2", "list"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            output = result.stdout
            if pm2_process_name in output and "online" in output.lower():
                log_success(f"PM2 process {pm2_process_name} is running")
                pm2_ok = True
            else:
                log_error(f"PM2 process {pm2_process_name} not found or not running")
        else:
            log_error(f"PM2 list failed: {result.stderr}")
            
    except Exception as e:
        log_error(f"PM2 check failed: {e}")
    
    return health_ok, root_ok, pm2_ok


def print_deployment_info(project: Dict) -> None:
    """Print deployment URLs and info."""
    domain = project.get("domain", "")
    base_domain = domain.split('.')[0] if '.' in domain else domain
    frontend_domain = f"{base_domain}.dreambigwithai.com"
    backend_domain = f"{base_domain}-api.dreambigwithai.com"
    
    print()
    print("=" * 60)
    print("DEPLOYMENT INFO")
    print("=" * 60)
    print(f"Project ID:    {project.get('id')}")
    print(f"Name:          {project.get('name')}")
    print(f"Status:        {project.get('status')}")
    print(f"Domain:        {base_domain}")
    print()
    print("URLs:")
    print(f"  Frontend:    http://{frontend_domain}")
    print(f"  Backend:     http://{backend_domain}")
    print(f"  Health:      http://{backend_domain}/health")
    print("=" * 60)


def run_pipeline_test(
    name: str,
    description: str = "",
    timeout: int = DEFAULT_TIMEOUT,
    agent_mode: bool = False,
    skip_verify: bool = False
) -> Dict:
    """
    Run full pipeline test.
    
    Returns result dict with status and URLs.
    """
    start_time = time.time()
    
    # Step 1: Create project
    project = create_project(name, description)
    if not project:
        return {
            "success": False,
            "error": "Failed to create project",
            "exit_code": 1
        }
    
    project_id = project["id"]
    domain = project["domain"]
    
    # Step 2: Monitor pipeline
    final_status, elapsed = poll_project_status(project_id, timeout, agent_mode)
    
    base_domain = domain.split('.')[0] if '.' in domain else domain
    result = {
        "project_id": project_id,
        "status": final_status,
        "domain": domain,
        "frontend_url": f"http://{base_domain}.dreambigwithai.com",
        "backend_url": f"http://{base_domain}-api.dreambigwithai.com",
        "pipeline_time": f"{elapsed // 60}m {elapsed % 60}s"
    }
    
    if final_status != "ready":
        result["success"] = False
        result["error"] = f"Pipeline ended with status: {final_status}"
        result["exit_code"] = 1 if final_status == "failed" else 2
        return result
    
    # Step 3: Verify deployment
    if not skip_verify:
        print()
        log_info("Running deployment verification...")
        print()
        
        dns_ok = check_dns(domain)
        frontend_ok = verify_frontend(domain)
        backend_ok = verify_backend(domain)
        pm2_fe, pm2_be = check_pm2(name)
        
        result["verification"] = {
            "dns": dns_ok,
            "frontend": frontend_ok,
            "backend": backend_ok,
            "pm2_frontend": pm2_fe,
            "pm2_backend": pm2_be
        }
        
        if not all([dns_ok, frontend_ok, backend_ok]):
            result["success"] = False
            result["error"] = "Infrastructure verification failed"
            result["exit_code"] = 3
            return result
    
    result["success"] = True
    result["exit_code"] = 0
    
    if not agent_mode:
        print_deployment_info(project)
        log_success(f"Pipeline completed in {result['pipeline_time']}")
    
    return result


def cmd_status(project_id: int) -> None:
    """Show project status."""
    log_info(f"Fetching project {project_id}...")
    
    project = get_project(project_id)
    if not project:
        log_error(f"Project {project_id} not found")
        sys.exit(1)
    
    print()
    print("=" * 50)
    print(f"PROJECT STATUS")
    print("=" * 50)
    print(f"ID:            {project.get('id')}")
    print(f"Name:          {project.get('name')}")
    print(f"Status:        {project.get('status')}")
    print(f"Domain:        {project.get('domain')}")
    print(f"Project Path:  {project.get('project_path', 'N/A')}")
    print(f"Template:      {project.get('template_id', 'N/A')}")
    print(f"Created:       {project.get('created_at')}")
    print("=" * 50)
    
    # Show pipeline status if available
    pipeline_status = project.get("pipeline_status", {})
    if pipeline_status:
        print()
        print("PIPELINE PHASES:")
        print("-" * 50)
        
        for phase_name in PHASE_NAMES.keys():
            phase_key = PHASE_NAMES[phase_name]
            phase_data = pipeline_status.get(phase_key, {})
            status = phase_data.get("status", "pending")
            
            if status == "completed":
                symbol = "✓"
            elif status == "running":
                symbol = "⏳"
            elif status == "failed":
                symbol = "✗"
            else:
                symbol = "○"
            
            print(f"  [{symbol}] {phase_name:12} {status}")
        
        print("-" * 50)


def run_telegram_pipeline_test(
    name: str,
    bot_token: str,
    description: str = "",
    timeout: int = DEFAULT_TIMEOUT,
    agent_mode: bool = False,
    skip_verify: bool = False
) -> Dict:
    """
    Run Telegram bot pipeline test.
    
    Returns result dict with status and bot info.
    """
    start_time = time.time()
    
    # Step 1: Create Telegram bot project
    project = create_project(name, description, type_id=2, bot_token=bot_token)
    if not project:
        return {
            "success": False,
            "error": "Failed to create Telegram bot project",
            "exit_code": 1
        }
    
    project_id = project["id"]
    domain = project["domain"]
    bot_port = project.get("bot_port", 8000 + (project_id % 1000))
    
    # Step 2: Monitor pipeline
    final_status, elapsed = poll_project_status(project_id, timeout, agent_mode)
    
    base_domain = domain.split('.')[0] if '.' in domain else domain
    result = {
        "project_id": project_id,
        "status": final_status,
        "domain": domain,
        "bot_port": bot_port,
        "webhook_url": f"https://{base_domain}-api.dreambigwithai.com/",
        "health_url": f"https://{base_domain}-api.dreambigwithai.com/health",
        "pm2_process": f"tg-bot-{project_id}",
        "pipeline_time": f"{elapsed // 60}m {elapsed % 60}s"
    }
    
    if final_status != "ready":
        result["success"] = False
        result["error"] = f"Pipeline ended with status: {final_status}"
        result["exit_code"] = 1 if final_status == "failed" else 2
        return result
    
    # Step 3: Verify Telegram bot deployment
    if not skip_verify:
        print()
        log_info("Running Telegram bot verification...")
        print()
        
        health_ok, root_ok, pm2_ok = verify_telegram_bot(project_id, domain)
        
        result["verification"] = {
            "health_endpoint": health_ok,
            "root_endpoint": root_ok,
            "pm2_process": pm2_ok
        }
        
        if not all([health_ok, root_ok, pm2_ok]):
            result["success"] = False
            result["error"] = "Telegram bot verification failed"
            result["exit_code"] = 3
            return result
    
    result["success"] = True
    result["exit_code"] = 0
    
    if not agent_mode:
        print()
        print("=" * 60)
        print("TELEGRAM BOT DEPLOYMENT INFO")
        print("=" * 60)
        print(f"Project ID:    {project_id}")
        print(f"Name:          {project.get('name')}")
        print(f"Status:        {final_status}")
        print(f"Bot Port:      {bot_port}")
        print(f"PM2 Process:   tg-bot-{project_id}")
        print()
        print("Endpoints:")
        print(f"  Webhook:     https://{base_domain}-api.dreambigwithai.com/")
        print(f"  Health:      https://{base_domain}-api.dreambigwithai.com/health")
        print("=" * 60)
        log_success(f"Pipeline completed in {result['pipeline_time']}")
    
    return result


def verify_scheduler(project_id: int) -> Tuple[bool, bool]:
    """
    Verify scheduler project deployment.

    Returns (jobs_api_ok, project_ready_ok)
    """
    log_check(f"Verifying scheduler project deployment...")

    jobs_api_ok = False
    project_ready_ok = False

    # Check scheduler jobs API (list jobs for project)
    jobs_url = f"{API_BASE_URL}/api/scheduler/projects/{project_id}/jobs"
    log_info(f"Checking scheduler jobs API: {jobs_url}")

    try:
        response = requests.get(jobs_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                job_count = data.get("count", 0)
                log_success(f"Scheduler jobs API verified ({job_count} jobs)")
                jobs_api_ok = True
            else:
                log_error(f"Unexpected API response: {data}")
        else:
            log_error(f"Scheduler jobs API returned {response.status_code}")
    except Exception as e:
        log_error(f"Scheduler jobs API check failed: {e}")

    # Check project logs API
    logs_url = f"{API_BASE_URL}/api/scheduler/projects/{project_id}/logs"
    log_info(f"Checking scheduler logs API: {logs_url}")

    try:
        response = requests.get(logs_url, timeout=10)
        if response.status_code == 200:
            log_success("Scheduler logs API verified")
            project_ready_ok = True
        else:
            log_error(f"Scheduler logs API returned {response.status_code}")
    except Exception as e:
        log_error(f"Scheduler logs API check failed: {e}")

    return jobs_api_ok, project_ready_ok


def run_scheduler_pipeline_test(
    name: str,
    description: str = "",
    timeout: int = DEFAULT_TIMEOUT,
    agent_mode: bool = False,
    skip_verify: bool = False
) -> Dict:
    """
    Run Scheduler project pipeline test.

    Returns result dict with status and project info.
    """
    # Step 1: Create scheduler project (no bot_token needed)
    project = create_project(name, description, type_id=5)
    if not project:
        return {
            "success": False,
            "error": "Failed to create scheduler project",
            "exit_code": 1
        }

    project_id = project["id"]

    # Step 2: Monitor pipeline
    final_status, elapsed = poll_project_status(project_id, timeout, agent_mode)

    result = {
        "project_id": project_id,
        "status": final_status,
        "domain": project.get("domain", ""),
        "project_path": project.get("project_path", ""),
        "jobs_api": f"{API_BASE_URL}/api/scheduler/projects/{project_id}/jobs",
        "pipeline_time": f"{elapsed // 60}m {elapsed % 60}s"
    }

    if final_status != "ready":
        result["success"] = False
        result["error"] = f"Pipeline ended with status: {final_status}"
        result["exit_code"] = 1 if final_status == "failed" else 2
        return result

    # Step 3: Verify scheduler deployment
    if not skip_verify:
        print()
        log_info("Running scheduler verification...")
        print()

        jobs_ok, logs_ok = verify_scheduler(project_id)

        result["verification"] = {
            "jobs_api": jobs_ok,
            "logs_api": logs_ok
        }

        if not all([jobs_ok, logs_ok]):
            result["success"] = False
            result["error"] = "Scheduler verification failed"
            result["exit_code"] = 3
            return result

    result["success"] = True
    result["exit_code"] = 0

    if not agent_mode:
        print()
        print("=" * 60)
        print("SCHEDULER PROJECT DEPLOYMENT INFO")
        print("=" * 60)
        print(f"Project ID:    {project_id}")
        print(f"Name:          {project.get('name')}")
        print(f"Status:        {final_status}")
        print()
        print("API Endpoints:")
        print(f"  Jobs:        {API_BASE_URL}/api/scheduler/projects/{project_id}/jobs")
        print(f"  Logs:        {API_BASE_URL}/api/scheduler/projects/{project_id}/logs")
        print()
        print("No PM2/nginx/DNS — centralized scheduler manages execution.")
        print("=" * 60)
        log_success(f"Pipeline completed in {result['pipeline_time']}")

    return result


def cmd_scheduler(args) -> int:
    """Handle scheduler command."""
    result = run_scheduler_pipeline_test(
        name=args.name,
        description=args.desc or "",
        timeout=args.timeout,
        agent_mode=args.agent,
        skip_verify=args.skip_verify
    )

    if args.agent:
        output = {
            "project_id": result.get("project_id"),
            "status": result.get("status"),
            "jobs_api": result.get("jobs_api"),
            "pipeline_time": result.get("pipeline_time"),
            "success": result.get("success")
        }
        print(json.dumps(output, indent=2))

    return result.get("exit_code", 1)


def cmd_create(args) -> int:
    """Handle create command."""
    result = run_pipeline_test(
        name=args.name,
        description=args.desc or "",
        timeout=args.timeout,
        agent_mode=args.agent,
        skip_verify=args.skip_verify
    )
    
    if args.agent:
        # JSON output for agent mode
        output = {
            "project_id": result.get("project_id"),
            "status": result.get("status"),
            "frontend_url": result.get("frontend_url"),
            "backend_url": result.get("backend_url"),
            "pipeline_time": result.get("pipeline_time"),
            "success": result.get("success")
        }
        print(json.dumps(output, indent=2))
    
    return result.get("exit_code", 1)


def cmd_telegram(args) -> int:
    """Handle telegram command."""
    result = run_telegram_pipeline_test(
        name=args.name,
        bot_token=args.token,
        description=args.desc or "",
        timeout=args.timeout,
        agent_mode=args.agent,
        skip_verify=args.skip_verify
    )

    if args.agent:
        # JSON output for agent mode
        output = {
            "project_id": result.get("project_id"),
            "status": result.get("status"),
            "webhook_url": result.get("webhook_url"),
            "health_url": result.get("health_url"),
            "pm2_process": result.get("pm2_process"),
            "bot_port": result.get("bot_port"),
            "pipeline_time": result.get("pipeline_time"),
            "success": result.get("success")
        }
        print(json.dumps(output, indent=2))

    return result.get("exit_code", 1)


def verify_discord_bot(project_id: int, domain: str) -> Tuple[bool, bool]:
    """
    Verify Discord bot deployment.

    Returns (health_ok, pm2_ok)
    """
    log_check(f"Verifying Discord bot deployment...")

    base_domain = domain.split('.')[0] if '.' in domain else domain
    bot_domain = f"{base_domain}.dreambigwithai.com"

    health_ok = False

    # Check health endpoint
    health_url = f"https://{bot_domain}/health"
    log_info(f"Checking health endpoint: {health_url}")

    try:
        response = requests.get(health_url, timeout=10, verify=True)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "healthy":
                log_success(f"Health endpoint verified")
                health_ok = True
            else:
                log_error(f"Unexpected health response: {data}")
        else:
            log_error(f"Health endpoint returned {response.status_code}")
    except requests.exceptions.SSLError:
        log_error(f"SSL certificate error for {bot_domain}")
    except Exception as e:
        log_error(f"Health endpoint check failed: {e}")

    # Check PM2 process
    pm2_process_name = f"dc-bot-{project_id}"
    log_info(f"Checking PM2 process: {pm2_process_name}")

    pm2_ok = False
    try:
        result = subprocess.run(
            ["pm2", "list"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            output = result.stdout
            if pm2_process_name in output and "online" in output.lower():
                log_success(f"PM2 process {pm2_process_name} is running")
                pm2_ok = True
            else:
                log_error(f"PM2 process {pm2_process_name} not found or not running")
        else:
            log_error(f"PM2 list failed: {result.stderr}")

    except Exception as e:
        log_error(f"PM2 check failed: {e}")

    return health_ok, pm2_ok


def run_discord_pipeline_test(
    name: str,
    bot_token: str,
    description: str = "",
    timeout: int = DEFAULT_TIMEOUT,
    agent_mode: bool = False,
    skip_verify: bool = False
) -> Dict:
    """
    Run Discord bot pipeline test.

    Returns result dict with status and bot info.
    """
    start_time = time.time()

    # Step 1: Create Discord bot project
    project = create_project(name, description, type_id=3, bot_token=bot_token)
    if not project:
        return {
            "success": False,
            "error": "Failed to create Discord bot project",
            "exit_code": 1
        }

    project_id = project["id"]
    domain = project["domain"]
    bot_port = 8000 + (project_id % 1000)

    # Step 2: Monitor pipeline
    final_status, elapsed = poll_project_status(project_id, timeout, agent_mode)

    base_domain = domain.split('.')[0] if '.' in domain else domain
    result = {
        "project_id": project_id,
        "status": final_status,
        "domain": domain,
        "bot_port": bot_port,
        "health_url": f"https://{base_domain}.dreambigwithai.com/health",
        "pm2_process": f"dc-bot-{project_id}",
        "pipeline_time": f"{elapsed // 60}m {elapsed % 60}s"
    }

    if final_status != "ready":
        result["success"] = False
        result["error"] = f"Pipeline ended with status: {final_status}"
        result["exit_code"] = 1 if final_status == "failed" else 2
        return result

    # Step 3: Verify Discord bot deployment
    if not skip_verify:
        print()
        log_info("Running Discord bot verification...")
        print()

        health_ok, pm2_ok = verify_discord_bot(project_id, domain)

        result["verification"] = {
            "health_endpoint": health_ok,
            "pm2_process": pm2_ok
        }

        if not all([health_ok, pm2_ok]):
            result["success"] = False
            result["error"] = "Discord bot verification failed"
            result["exit_code"] = 3
            return result

    result["success"] = True
    result["exit_code"] = 0

    if not agent_mode:
        print()
        print("=" * 60)
        print("DISCORD BOT DEPLOYMENT INFO")
        print("=" * 60)
        print(f"Project ID:    {project_id}")
        print(f"Name:          {project.get('name')}")
        print(f"Status:        {final_status}")
        print(f"Bot Port:      {bot_port}")
        print(f"PM2 Process:   dc-bot-{project_id}")
        print()
        print("Endpoints:")
        print(f"  Health:      https://{base_domain}.dreambigwithai.com/health")
        print("=" * 60)
        log_success(f"Pipeline completed in {result['pipeline_time']}")

    return result


def cmd_discord(args) -> int:
    """Handle discord command."""
    result = run_discord_pipeline_test(
        name=args.name,
        bot_token=args.token,
        description=args.desc or "",
        timeout=args.timeout,
        agent_mode=args.agent,
        skip_verify=args.skip_verify
    )

    if args.agent:
        output = {
            "project_id": result.get("project_id"),
            "status": result.get("status"),
            "health_url": result.get("health_url"),
            "pm2_process": result.get("pm2_process"),
            "bot_port": result.get("bot_port"),
            "pipeline_time": result.get("pipeline_time"),
            "success": result.get("success")
        }
        print(json.dumps(output, indent=2))

    return result.get("exit_code", 1)


def main():
    parser = argparse.ArgumentParser(
        description="DreamPilot Deployment Tester",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  dreamtest create --name "Test App" --desc "Pipeline test"
  dreamtest create --name "Agent Test" --agent
  dreamtest create --ci
  dreamtest telegram --name "My Bot" --token "123:abc"
  dreamtest discord --name "My Bot" --token "MTIz.abc.def"
  dreamtest scheduler --name "BTC Tracker" --desc "Send BTC price every 10m"
  dreamtest status 123
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Create command
    create_parser = subparsers.add_parser("create", help="Create and test a new project")
    create_parser.add_argument("--name", "-n", required=True, help="Project name")
    create_parser.add_argument("--desc", "-d", default="", help="Project description")
    create_parser.add_argument("--timeout", "-t", type=int, default=DEFAULT_TIMEOUT,
                               help=f"Pipeline timeout in seconds (default: {DEFAULT_TIMEOUT})")
    create_parser.add_argument("--agent", "-a", action="store_true",
                               help="Agent mode - output JSON only")
    create_parser.add_argument("--ci", action="store_true",
                               help="CI mode - use exit codes")
    create_parser.add_argument("--skip-verify", action="store_true",
                               help="Skip infrastructure verification")
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Show project status")
    status_parser.add_argument("project_id", type=int, help="Project ID")
    
    # Telegram command
    telegram_parser = subparsers.add_parser("telegram", help="Create and test a Telegram bot")
    telegram_parser.add_argument("--name", "-n", required=True, help="Bot name")
    telegram_parser.add_argument("--token", "-t", required=True, help="Bot token from @BotFather")
    telegram_parser.add_argument("--desc", "-d", default="", help="Bot description")
    telegram_parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                                 help=f"Pipeline timeout in seconds (default: {DEFAULT_TIMEOUT})")
    telegram_parser.add_argument("--agent", "-a", action="store_true",
                                 help="Agent mode - output JSON only")
    telegram_parser.add_argument("--skip-verify", action="store_true",
                                 help="Skip bot verification")

    # Discord command
    discord_parser = subparsers.add_parser("discord", help="Create and test a Discord bot")
    discord_parser.add_argument("--name", "-n", required=True, help="Bot name")
    discord_parser.add_argument("--token", "-t", required=True, help="Bot token from Discord Developer Portal")
    discord_parser.add_argument("--desc", "-d", default="", help="Bot description")
    discord_parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                                help=f"Pipeline timeout in seconds (default: {DEFAULT_TIMEOUT})")
    discord_parser.add_argument("--agent", "-a", action="store_true",
                                help="Agent mode - output JSON only")
    discord_parser.add_argument("--skip-verify", action="store_true",
                                help="Skip bot verification")

    # Scheduler command
    scheduler_parser = subparsers.add_parser("scheduler", help="Create and test a Scheduler project")
    scheduler_parser.add_argument("--name", "-n", required=True, help="Project name")
    scheduler_parser.add_argument("--desc", "-d", default="", help="Project description")
    scheduler_parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                                  help=f"Pipeline timeout in seconds (default: {DEFAULT_TIMEOUT})")
    scheduler_parser.add_argument("--agent", "-a", action="store_true",
                                  help="Agent mode - output JSON only")
    scheduler_parser.add_argument("--skip-verify", action="store_true",
                                  help="Skip API verification")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "create":
        exit_code = cmd_create(args)
        sys.exit(exit_code)

    elif args.command == "telegram":
        exit_code = cmd_telegram(args)
        sys.exit(exit_code)

    elif args.command == "discord":
        exit_code = cmd_discord(args)
        sys.exit(exit_code)

    elif args.command == "scheduler":
        exit_code = cmd_scheduler(args)
        sys.exit(exit_code)

    elif args.command == "status":
        cmd_status(args.project_id)
        sys.exit(0)


if __name__ == "__main__":
    main()