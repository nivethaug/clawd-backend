#!/usr/bin/env python3
"""
Direct test of router and navigation update
"""
from openclaw_wrapper import OpenClawWrapper
from pathlib import Path

# Use project 485 (most recent complete project)
frontend_path = Path("/root/dreampilot/projects/website/485_Router Validation Final_20260309_001337/frontend/src")
pages = ["Dashboard", "Analytics", "Settings", "Tasks", "Create"]

print("🎯 Testing router + navigation update")
print(f"📁 Frontend path: {frontend_path}")
print(f"📄 Pages: {pages}")

# Create minimal wrapper instance
class TestWrapper:
    def __init__(self):
        self.frontend_path = frontend_path
        self.project_name = "Test"
        self.description = "Test"

# Import the method
wrapper = TestWrapper()

# Get the actual method from OpenClawWrapper
wrapper_method = OpenClawWrapper._update_router_and_navigation

# Call it
print("\n🔧 Running _update_router_and_navigation()...")
result = wrapper_method(wrapper, pages)

print(f"\n✅ Result:")
print(f"   Router updated: {result.get('router_updated', False)}")
print(f"   Navigation updated: {result.get('navigation_updated', False)}")
print(f"   Imports added: {result.get('imports_added', 0)}")
print(f"   Routes added: {result.get('routes_added', 0)}")
print(f"   Nav items added: {result.get('nav_items_added', 0)}")
print(f"   Errors: {result.get('errors', [])}")

print("\n📄 Checking App.tsx...")
app_tsx = frontend_path / "App.tsx"
if app_tsx.exists():
    content = app_tsx.read_text()
    print(f"   Routes found: {('<Route' in content)}")
    print(f"   Dashboard import: {('Dashboard' in content)}")
    print(f"   Analytics import: {('Analytics' in content)}")
    print(f"   Settings import: {('Settings' in content)}")
    print(f"   Tasks import: {('Tasks' in content)}")
    print(f"   Create import: {('Create' in content)}")
else:
    print("❌ App.tsx not found!")

print("\n📄 Checking AppLayout.tsx...")
app_layout = frontend_path.parent / "app" / "layouts" / "AppLayout.tsx"
if app_layout.exists():
    content = app_layout.read_text()
    print(f"   mainNavItems found: {('mainNavItems' in content)}")
    print(f"   Dashboard in nav: {('Dashboard' in content)}")
    print(f"   Analytics in nav: {('Analytics' in content)}")
    print(f"   Settings in nav: {('Settings' in content)}")
    print(f"   Tasks in nav: {('Tasks' in content)}")
else:
    print("❌ AppLayout.tsx not found!")
