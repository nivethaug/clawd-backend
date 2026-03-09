#!/usr/bin/env python3
"""
Test script to debug router update issues
"""
import sys
import os
from pathlib import Path
sys.path.append('/root/clawd-backend')

# Test project 486 paths
project_path = "/root/dreampilot/projects/website/486_Debug Router Test_20260309_001740"
project_name = "Debug Router Test"
description = "CRM with Dashboard, Analytics pages"

# Create a mock OpenClawWrapper instance
class MockWrapper:
    def __init__(self):
        self.project_path = Path(project_path)
        self.project_name = project_name
        self.description = description
        self.frontend_path = Path(project_path) / 'frontend'

    def _update_router_and_navigation(self, pages: list):
        """
        Test the router update method
        """
        import re
        
        app_tsx_path = self.frontend_path / "src" / "App.tsx"
        app_layout_path = self.frontend_path / "src" / "app" / "layouts" / "AppLayout.tsx"
        
        results = {
            "router_updated": False,
            "navigation_updated": False,
            "imports_added": 0,
            "routes_added": 0,
            "nav_items_added": 0,
            "errors": []
        }
        
        print(f"🔧 Testing router update for pages: {pages}")
        print(f"📁 App.tsx path: {app_tsx_path}")
        print(f"📁 AppLayout.tsx path: {app_layout_path}")
        
        # Icon mappings for common pages from lucide-react
        icon_mappings = {
            "dashboard": "LayoutDashboard",
            "analytics": "BarChart3",
            "contacts": "Users",
            "tasks": "CheckSquare",
            "settings": "Settings",
            "documents": "FileText",
            "templates": "Copy",
            "editor": "FileEdit",
            "signing": "PenTool",
            "create": "PlusCircle",
        }
        
        try:
            # Update App.tsx - Add imports and routes
            print("🔧 Testing React Router (App.tsx)...")
            
            if app_tsx_path.exists():
                app_tsx_content = app_tsx_path.read_text()
                print(f"📄 App.tsx content (first 500 chars):")
                print(app_tsx_content[:500])
                
                # Add imports for new pages
                imports_to_add = []
                for page in pages:
                    # Add import for ALL pages
                    import_line_double = f'import {page} from "./pages/{page}";'
                    # Check if import already exists (try both single and double quotes)
                    if (import_line_double not in app_tsx_content and
                        f"import {page} from '@/pages/{page}'" not in app_tsx_content):
                        # Use double quotes (standard format)
                        imports_to_add.append(import_line_double)
                
                print(f"📥 Imports to add: {imports_to_add}")
                
                # Find last import line and insert new imports
                import_pattern = r'(import .+ from ["\']./pages/[^"\']+["\'])'
                last_import_match = None
                for match in re.finditer(import_pattern, app_tsx_content):
                    last_import_match = match
                
                if last_import_match and imports_to_add:
                    insert_pos = last_import_match.end()
                    new_imports = "\n" + "\n".join(imports_to_add)
                    app_tsx_content = (
                        app_tsx_content[:insert_pos] + 
                        new_imports + 
                        app_tsx_content[insert_pos:]
                    )
                    results["imports_added"] = len(imports_to_add)
                    print(f"✅ Added {len(imports_to_add)} imports")
                else:
                    print(f"⚠️ No imports added - last_import_match: {last_import_match}, imports_to_add: {len(imports_to_add)}")
                
                # Add routes for new pages
                routes_to_add = []
                for page in pages:
                    page_lower = page.lower()
                    # Generate routes for ALL pages, not just those in route_mappings
                    route_path = f"/{page_lower}"
                    route_line = f'          <Route path="{route_path}" element={{{page}}} />'
                    # Check if route already exists
                    if f'path="{route_path}"' not in app_tsx_content:
                        routes_to_add.append((page, route_path, route_line))
                        print(f"🛣️ Will add route: {page} → {route_path}")
                    else:
                        print(f"🚫 Route already exists: {route_path}")
                
                if routes_to_add:
                    # Find </Routes> tag and insert before it
                    routes_end_pattern = '</Routes>'
                    routes_end_pos = app_tsx_content.find(routes_end_pattern)
                    
                    if routes_end_pos != -1:
                        # Generate route block
                        route_block = ""
                        for page, route_path, route_line in routes_to_add:
                            route_block += route_line + "\n"
                        
                        # Insert before </Routes>
                        app_tsx_content = (
                            app_tsx_content[:routes_end_pos] +
                            route_block +
                            app_tsx_content[routes_end_pos:]
                        )
                        results["routes_added"] = len(routes_to_add)
                        results["router_updated"] = True
                        print(f"✅ Added {len(routes_to_add)} routes: {[r[0] for r in routes_to_add]}")
                    else:
                        print(f"❌ Could not find </Routes> tag in App.tsx")
                        print(f"   Content: {app_tsx_content}")
                        results["errors"].append("Could not find </Routes> tag")
                else:
                    print(f"🤷 No routes to add")
                
                # Write back if changes made
                if results["imports_added"] > 0 or results["routes_added"] > 0:
                    print("📝 Writing changes to App.tsx...")
                    app_tsx_path.write_text(app_tsx_content)
                    print(f"✅ App.tsx updated")
                    
                    # Show updated content
                    print(f"📄 Updated App.tsx:")
                    updated_content = app_tsx_path.read_text()
                    print(updated_content[:1000])
                else:
                    print(f"🤷 No router changes needed (already up to date)")
                
            else:
                print(f"❌ App.tsx not found: {app_tsx_path}")
                results["errors"].append("App.tsx not found")
                
        except Exception as e:
            print(f"❌ Exception updating App.tsx: {e}")
            results["errors"].append(f"App.tsx error: {str(e)}")
        
        return results

# Test it
mock = MockWrapper()
test_pages = ["Dashboard", "Analytics", "Contacts", "Tasks", "Create"]
result = mock._update_router_and_navigation(test_pages)

print(f"\n🎯 ROUTER RESULTS: {result}")
        
        except Exception as e:
            print(f"❌ Exception updating App.tsx: {e}")
            results["errors"].append(f"App.tsx error: {str(e)}")
        
        return results

# Test it
mock = MockWrapper()
test_pages = ["Dashboard", "Analytics", "Contacts", "Tasks", "Create"]
result = mock._update_router_and_navigation(test_pages)

print(f"\n🎯 ROUTER RESULTS: {result}")

# Now test navigation update
print(f"\n🔧 Testing navigation update...")
try:
    # Update AppLayout.tsx - Add navigation items
    app_layout_path = mock.frontend_path / "src" / "app" / "layouts" / "AppLayout.tsx"
    if app_layout_path.exists():
        app_layout_content = app_layout_path.read_text()
        print(f"📄 AppLayout.tsx content (mainNavItems section):")
        mainnav_match = re.search(r'const mainNavItems = \[(.*?)\];', app_layout_content, re.DOTALL)
        if mainnav_match:
            print(mainnav_match.group(0))
        else:
            print("❌ Could not find mainNavItems array")
            
except Exception as e:
    print(f"❌ Navigation test failed: {e}")