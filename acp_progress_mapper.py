#!/usr/bin/env python3
"""
ACP Progress Mapper - Maps Claude's raw log lines to friendly user messages.

Zero API cost - pure keyword matching.
Deduplicates messages so user doesn't see same message twice in a row.
"""

from datetime import datetime
from typing import Optional


class ClaudeProgressMapper:
    """
    Maps Claude's raw log lines to friendly user messages.
    Zero API cost - pure keyword matching.
    Deduplicates messages so user doesn't see same message twice in a row.
    """
    
    PROGRESS_MAP = [
        # Tool names from stream-json (highest priority - match TOOL: prefix first)
        ("TOOL:Bash",               "⚙️ Running a command..."),
        ("TOOL:Read",               "📄 Reading project files..."),
        ("TOOL:Edit",               "✏️ Making changes to your app..."),
        ("TOOL:Write",              "📝 Writing new code..."),
        ("TOOL:MultiEdit",          "✏️ Making multiple changes..."),
        ("TOOL:Glob",               "🔍 Exploring your project files..."),
        ("TOOL:Grep",               "🔎 Searching through your code..."),
        ("TOOL:Task",               "📋 Planning changes..."),
        ("TOOL:TodoWrite",          "📋 Updating task list..."),
        ("TOOL:WebSearch",          "🔍 Searching the web..."),
        ("TOOL:WebFetch",           "🌐 Fetching web content..."),
        ("TOOL:mcp__chrome-devtools__new_page",              "🌐 Opening your live site..."),
        ("TOOL:mcp__chrome-devtools__navigate_page",         "🧭 Navigating to page..."),
        ("TOOL:mcp__chrome-devtools__take_screenshot",       "📸 Taking a screenshot..."),
        ("TOOL:mcp__chrome-devtools__take_snapshot",         "📸 Capturing page state..."),
        ("TOOL:mcp__chrome-devtools__list_console_messages", "🔍 Checking for errors..."),
        ("TOOL:mcp__chrome-devtools__click",                 "🖱️ Testing interactions..."),
        ("TOOL:mcp__chrome-devtools__fill",                  "📝 Testing your forms..."),
        ("TOOL:mcp__chrome-devtools__press_key",             "⌨️ Testing keyboard input..."),
        ("TOOL:mcp__chrome-devtools__close_page",            "✅ Browser testing complete!"),
        
        # Agent README / Planning
        ("readme",                  "📖 Reading your project guide..."),
        ("agent/readme",            "📖 Reading your project guide..."),
        ("ai_index",                "🗂️ Loading project index..."),
        ("todowrite",               "📋 Planning the changes..."),
        ("planning",                "📋 Planning the changes..."),
        
        # File Exploration
        ("glob",                    "🔍 Exploring your project files..."),
        ("grep",                    "🔎 Searching through your code..."),
        ("ls ",                     "📁 Checking project structure..."),
        ("find ",                   "🔍 Looking for relevant files..."),
        
        # Reading Files
        ("read",                    "📄 Reading project files..."),
        ("cat ",                    "📄 Reading project files..."),
        
        # Git / Branching
        ("git checkout -b",         "🌿 Setting up a safe workspace..."),
        ("git checkout",            "🌿 Switching to workspace..."),
        ("git merge",               "✅ Applying your approved changes..."),
        ("git commit",              "💾 Saving progress..."),
        ("git push",                "☁️ Uploading changes..."),
        ("git status",              "🔍 Checking workspace status..."),
        ("git diff",                "🔍 Reviewing changes..."),
        
        # Code Editing
        ("edit",                    "✏️ Making changes to your app..."),
        ("write",                   "📝 Writing new code..."),
        ("multiedit",               "✏️ Making multiple changes..."),
        ("create",                  "🆕 Creating new features..."),
        
        # npm / Dependencies  
        ("npm ci",                  "📦 Installing dependencies..."),
        ("npm install",             "📦 Installing dependencies..."),
        ("npm run build",           "🔨 Building your app..."),
        ("yarn install",            "📦 Installing dependencies..."),
        
        # Vite Build
        ("vite build",              "🔨 Building your app..."),
        ("transforming",            "⚙️ Compiling your app..."),
        ("modules transformed",     "⚙️ Compiling your app..."),
        ("dist verified",           "✅ Build successful!"),
        
        # buildpublish
        ("buildpublish",            "🚀 Publishing your changes..."),
        ("build & publish complete","🎉 Changes published successfully!"),
        ("install-only",            "📦 Installing dependencies..."),
        ("clean vite",              "🧹 Cleaning old build files..."),
        ("remove node_modules",     "🧹 Cleaning up..."),
        ("fix permissions",         "🔒 Setting file permissions..."),
        ("cleanup node_modules",    "🧹 Freeing up space..."),
        
        # PM2
        ("pm2 restart",             "🔄 Restarting your app server..."),
        ("pm2 start",               "▶️ Starting your app server..."),
        ("pm2 stop",                "⏹️ Stopping server..."),
        ("pm2 reload",              "🔄 Reloading your app..."),
        ("pm2",                     "⚙️ Managing app server..."),
        
        # Nginx
        ("nginx -s reload",         "🌐 Updating web server..."),
        ("nginx",                   "🌐 Configuring web server..."),
        
        # Chrome DevTools - Navigation
        ("new_page",                "🌐 Opening your live site..."),
        ("navigate_page",           "🧭 Navigating to page..."),
        ("close_page",              "✅ Browser testing complete!"),
        
        # Chrome DevTools - Testing
        ("take_screenshot",         "📸 Taking a screenshot..."),
        ("take_snapshot",           "📸 Capturing page state..."),
        ("list_console_messages",   "🔍 Checking for errors..."),
        ("get_console_messages",    "🔍 Checking for errors..."),
        ("click",                   "🖱️ Testing app interactions..."),
        ("fill",                    "📝 Testing your forms..."),
        ("press_key",               "⌨️ Testing keyboard input..."),
        ("scroll",                  "📜 Scrolling through page..."),
        ("hover",                   "🖱️ Checking hover effects..."),
        ("evaluate",                "🔬 Running browser checks..."),
        ("wait_for",                "⏳ Waiting for page to load..."),
        
        # Database
        ("migration",               "🗄️ Updating your database..."),
        ("alter table",             "🗄️ Modifying database structure..."),
        ("create table",            "🗄️ Creating new database tables..."),
        ("drop table",              "🗄️ Removing old database tables..."),
        ("insert into",             "🗄️ Adding data to database..."),
        ("select ",                 "🗄️ Reading from database..."),
        ("postgresql",              "🗄️ Working with database..."),
        ("psql",                    "🗄️ Running database command..."),
        
        # Python / Backend
        ("pip install",             "📦 Installing Python packages..."),
        ("python3",                 "🐍 Running Python script..."),
        ("fastapi",                 "⚡ Updating API server..."),
        ("uvicorn",                 "⚡ Starting API server..."),
        
        # Agent Index Updates
        ("symbols.json",            "🗂️ Updating project index..."),
        ("modules.json",            "🗂️ Updating project index..."),
        ("summaries.json",          "🗂️ Updating project index..."),
        ("files.json",              "🗂️ Updating project index..."),
        ("database_schema.json",    "🗂️ Updating database index..."),
        
        # Success / Completion
        ("success",                 "✅ Step completed successfully!"),
        ("completed",               "✅ Step completed!"),
        ("done",                    "✅ Step done!"),
        ("finished",                "✅ All done!"),
        
        # Errors / Fixing
        ("error",                   "🔧 Found an issue, fixing it..."),
        ("fix",                     "🔧 Applying a fix..."),
        ("retry",                   "🔄 Retrying..."),
        ("fallback",                "🔄 Trying another approach..."),
    ]
    
    # Phase messages based on elapsed time
    PHASE_MESSAGES = [
        (0,   "🔍 Analyzing your request..."),
        (30,  "✨ Working on your changes..."),
        (120, "🔧 Applying improvements..."),
        (300, "⚙️ Processing complex task..."),
        (600, "🎯 Almost there, finalizing..."),
    ]
    
    def __init__(self):
        self.last_message = ""
        self.message_count = 0
    
    def get_friendly_message(self, raw_line: str) -> Optional[str]:
        """
        Match raw log line to friendly message.
        Returns None if no match or duplicate.
        """
        if not raw_line or not raw_line.strip():
            return None
        
        line_lower = raw_line.lower().strip()
        
        # Skip pure noise lines
        noise = ["null", "{}", "[]", "---", "===", ">>>", "<<<"]
        if line_lower in noise:
            return None
        
        # Match against keyword map
        for keyword, message in self.PROGRESS_MAP:
            if keyword.lower() in line_lower:
                # Deduplicate — skip if same as last message
                if message == self.last_message:
                    return None
                self.last_message = message
                self.message_count += 1
                return message
        
        return None
    
    def get_phase_message(self, elapsed_seconds: float) -> str:
        """Get phase-based message for progress timeouts."""
        message = self.PHASE_MESSAGES[0][1]
        for threshold, msg in self.PHASE_MESSAGES:
            if elapsed_seconds >= threshold:
                message = msg
        return message
    
    def reset(self):
        """Reset state for new session."""
        self.last_message = ""
        self.message_count = 0


# Quick unit test
if __name__ == "__main__":
    mapper = ClaudeProgressMapper()
    test_lines = [
        "Reading frontend/agent/README.md",
        "npm ci running...",
        "vite build transforming modules",
        "pm2 restart thinkai-frontend",
        "take_screenshot completed",
        "list_console_messages",
        "build & publish complete",
    ]
    print("Testing ClaudeProgressMapper:")
    print("-" * 80)
    for line in test_lines:
        msg = mapper.get_friendly_message(line)
        print(f"{line[:40]:<40} → {msg}")
    print("-" * 80)
    print(f"Messages generated: {mapper.message_count}")
