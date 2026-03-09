#!/usr/bin/env python3
"""Test keyword detection"""

description = "CRM with Dashboard, Analytics, Settings pages"
desc_lower = description.lower()

required_pages = []

# Detect pages based on keywords
if any(word in desc_lower for word in ['dashboard', 'overview']):
    required_pages.append('Dashboard')
    print(f"✅ Dashboard detected (keywords: dashboard, overview)")
    
if any(word in desc_lower for word in ['document', 'docflow', 'panda', 'agreement', 'contract']):
    required_pages.extend(['Documents', 'DocumentEditor', 'Templates', 'Signing'])
    print(f"✅ Documents detected (keywords: document, docflow, panda, agreement, contract)")
    
if any(word in desc_lower for word in ['analytics', 'reports', 'metrics']):
    required_pages.append('Analytics')
    print(f"✅ Analytics detected (keywords: analytics, reports, metrics)")
    
if any(word in desc_lower for word in ['contact', 'crm', 'customer', 'lead']):
    required_pages.append('Contacts')
    print(f"✅ Contacts detected (keywords: contact, crm, customer, lead)")
    
if any(word in desc_lower for word in ['task', 'todo', 'project', 'kanban']):
    required_pages.append('Tasks')
    print(f"✅ Tasks detected (keywords: task, todo, project, kanban)")
    
if any(word in desc_lower for word in ['setting', 'config', 'preference']):
    required_pages.append('Settings')
    print(f"✅ Settings detected (keywords: setting, config, preference)")
    
if any(word in desc_lower for word in ['post', 'article', 'blog']):
    required_pages.append('Posts')
    print(f"✅ Posts detected (keywords: post, article, blog)")
    
if any(word in desc_lower for word in ['create', 'write', 'compose']):
    required_pages.append('Create')
    print(f"✅ Create detected (keywords: create, write, compose)")

# Deduplicate
result = list(set(required_pages))

print(f"\n🎯 Result: {result}")
print(f"🎯 Deduped: {len(required_pages)} -> {len(result)} pages")
