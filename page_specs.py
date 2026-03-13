#!/usr/bin/env python3
"""
Page Specifications System (Phase 4)

Provides detailed UI component specifications for each page type.
Instead of simple page names, planner outputs page specs with
detailed component requirements.

Example:
    Dashboard → metric cards + charts + activity table
    Reports → table + filters + export
"""

import logging

logger = logging.getLogger(__name__)

# Page specifications with detailed component requirements
PAGE_SPECS = {
    "Dashboard": {
        "components": ["metric_cards", "line_chart", "activity_table", "responsive_layout"],
        "description": "Main dashboard with metrics, charts, and recent activity",
        "ui_elements": [
            "4 metric cards showing key KPIs",
            "Line chart for trend visualization",
            "Recent activity table with timestamp",
            "Responsive grid layout",
            "Loading states for all components"
        ],
        "icon": "LayoutDashboard"
    },
    
    "Documents": {
        "components": ["document_list", "filters", "status_badges", "upload_button"],
        "description": "Document management with listing and filters",
        "ui_elements": [
            "Sortable document table",
            "Filter controls (date, status, type)",
            "Status badges for each document",
            "Upload button with drag-drop support",
            "Bulk actions toolbar"
        ],
        "icon": "FileText"
    },
    
    "Templates": {
        "components": ["template_list", "preview", "use_template_button"],
        "description": "Template library with preview functionality",
        "ui_elements": [
            "Grid layout of templates",
            "Thumbnail previews for each template",
            "Category filters",
            "Search functionality",
            "'Use Template' button for selection"
        ],
        "icon": "Copy"
    },
    
    "DocumentEditor": {
        "components": ["rich_text_editor", "toolbar", "save_button", "preview"],
        "description": "Rich text document editor",
        "ui_elements": [
            "WYSIWYG editor (TipTap or similar)",
            "Formatting toolbar (bold, italic, lists, etc.)",
            "Auto-save functionality",
            "Preview mode toggle",
            "Export options (PDF, DOCX)"
        ],
        "icon": "FileEdit"
    },
    
    "Signing": {
        "components": ["signature_pad", "document_viewer", "sign_button", "timestamp"],
        "description": "Electronic signature interface",
        "ui_elements": [
            "Document viewer with pagination",
            "Canvas-based signature pad",
            "Sign button with confirmation",
            "Timestamp and date stamp",
            "Signature history or log"
        ],
        "icon": "PenTool"
    },
    
    "Analytics": {
        "components": ["charts", "metrics", "filters", "export"],
        "description": "Analytics dashboard with data visualization",
        "ui_elements": [
            "Multiple chart types (bar, line, pie)",
            "Date range filters",
            "Metric summary cards",
            "Export to CSV/PDF",
            "Real-time data refresh"
        ],
        "icon": "BarChart3"
    },
    
    "Contacts": {
        "components": ["contact_list", "search", "add_contact", "bulk_actions"],
        "description": "Contact management database",
        "ui_elements": [
            "Searchable contact table",
            "Add new contact button",
            "Contact details modal",
            "Bulk import/export",
            "Contact tags or groups"
        ],
        "icon": "Users"
    },
    
    "Team": {
        "components": ["team_list", "member_roles", "invite_button", "permissions"],
        "description": "Team management with role-based access",
        "ui_elements": [
            "Team members list with avatars",
            "Role assignment dropdown",
            "Invite member button/email input",
            "Permission toggles",
            "Activity timeline per member"
        ],
        "icon": "Users"
    },
    
    "Billing": {
        "components": ["subscription_details", "payment_methods", "invoice_history", "upgrade_options"],
        "description": "Billing and subscription management",
        "ui_elements": [
            "Current plan details card",
            "Payment method management",
            "Invoice history table",
            "Upgrade/downgrade options",
            "Usage metrics display"
        ],
        "icon": "CreditCard"
    },
    
    "Notifications": {
        "components": ["notification_list", "filters", "mark_read", "settings"],
        "description": "Notification center with filtering",
        "ui_elements": [
            "Notification list with icons",
            "Read/unread status",
            "Filter by type (alerts, updates, etc.)",
            "Mark all as read button",
            "Notification preferences link"
        ],
        "icon": "Bell"
    },
    
    "Tasks": {
        "components": ["task_list", "kanban_board", "add_task", "drag_drop"],
        "description": "Task management with Kanban board",
        "ui_elements": [
            "Kanban-style columns (To Do, In Progress, Done)",
            "Drag and drop task cards",
            "Task creation form",
            "Task details modal",
            "Priority indicators and due dates"
        ],
        "icon": "KanbanBoard"
    },
    
    "Settings": {
        "components": ["settings_form", "tabbed_navigation", "save_button", "validation"],
        "description": "Application settings management",
        "ui_elements": [
            "Tabbed navigation (Profile, Security, Preferences)",
            "Form fields for each setting",
            "Save/Cancel buttons",
            "Form validation feedback",
            "Success/error toast notifications"
        ],
        "icon": "Settings"
    },
    
    "Posts": {
        "components": ["post_list", "editor", "categories", "publish_button"],
        "description": "Blog post management",
        "ui_elements": [
            "Post list with status badges",
            "Rich text editor",
            "Category/tag selection",
            "Publish/Draft/Schedule buttons",
            "Featured image upload"
        ],
        "icon": "FileText"
    },
    
    "Create": {
        "components": ["content_editor", "template_selector", "preview", "publish"],
        "description": "Content creation interface",
        "ui_elements": [
            "Rich content editor",
            "Template selector sidebar",
            "Live preview panel",
            "Publish button with options",
            "Auto-save draft"
        ],
        "icon": "Plus"
    },
    
    "Deals": {
        "components": ["deal_pipeline", "deal_cards", "stage_management", "add_deal"],
        "description": "CRM deal pipeline management",
        "ui_elements": [
            "Pipeline view with columns (stages)",
            "Deal cards with value and contact",
            "Drag deals between stages",
            "Stage management (add/edit/delete)",
            "Add new deal button"
        ],
        "icon": "TrendingUp"
    },
    
    "Reports": {
        "components": ["report_list", "date_filters", "generate_button", "export"],
        "description": "Reports generation and viewing",
        "ui_elements": [
            "Report type selector",
            "Date range filters",
            "Generate report button",
            "Table view of results",
            "Export to CSV/PDF/Excel"
        ],
        "icon": "BarChart"
    }
}

def get_page_spec(page_name: str) -> dict:
    """
    Get page specification for a given page name.

    Args:
        page_name: Name of the page (e.g., "Dashboard", "Analytics")

    Returns:
        Dict with page specification or None if not found
    """
    spec = PAGE_SPECS.get(page_name)
    if spec:
        logger.info(f"[PageSpec] Found spec for {page_name}: {spec['components']}")
    else:
        logger.warning(f"[PageSpec] No spec found for {page_name}, using defaults")
    return spec

def get_all_page_specs() -> dict:
    """Get all page specifications."""
    return PAGE_SPECS

def format_page_spec_for_prompt(page_name: str, spec: dict) -> str:
    """
    Format page specification for ACPX prompt.

    Args:
        page_name: Name of the page
        spec: Page specification dict

    Returns:
        Formatted string for ACPX prompt
    """
    components_str = ", ".join(spec['components'])
    ui_elements_str = "\n".join([f"- {elem}" for elem in spec['ui_elements']])
    
    return f"""
## Page: {page_name} ({spec['description']})

Required Components:
{components_str}

UI Elements to Include:
{ui_elements_str}

Implementation Notes:
- Use {spec['icon']} icon from lucide-react
- Follow existing component patterns
- Ensure responsive design
- Add proper loading states
- Include error handling
---
"""

def format_page_spec_list(page_names: list) -> list:
    """
    Format multiple page specifications for ACPX prompt.

    Args:
        page_names: List of page names

    Returns:
        List of formatted spec strings
    """
    specs = []
    for page_name in page_names:
        spec = get_page_spec(page_name)
        if spec:
            specs.append(format_page_spec_for_prompt(page_name, spec))
    return specs
