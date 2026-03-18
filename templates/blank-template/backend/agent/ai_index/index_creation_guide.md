# AI Index Creation Guide

You are an expert AI systems engineer.

Your task is to analyze a large brownfield codebase and generate a structured **AI Index** optimized for LLM-based code understanding, retrieval, and editing.

The codebase may contain hundreds of thousands to millions of lines across multiple modules.

---

## 🎯 OBJECTIVE

Generate a complete **AI Index** that enables efficient:

* semantic search
* dependency reasoning
* code navigation
* safe code editing

---

## 📦 OUTPUT FORMAT (STRICT JSON FILES)

Generate the following files:

1. `modules.json`
2. `symbols.json`
3. `dependencies.json`
4. `summaries.json`
5. `files.json` (optional but recommended)

---

## 📁 1. modules.json

Group files into logical modules.

Format:

```json
{
  "leads": {
    "files": ["src/leads/lead_service.py", "src/leads/lead_controller.py"],
    "description": "Handles lead lifecycle and conversion"
  }
}
```

---

## 🔎 2. symbols.json (CRITICAL)

Extract ALL functions, classes, and important symbols.

Include:

* name
* type (function/class/api)
* file path
* start_line
* end_line
* module
* dependencies (if possible)

Format:

```json
{
  "create_lead": {
    "type": "function",
    "file": "src/leads/lead_service.py",
    "start_line": 45,
    "end_line": 92,
    "module": "leads",
    "dependencies": ["LeadRepository", "EmailValidator"]
  }
}
```

---

## 🔗 3. dependencies.json

Map relationships between files/modules.

Include:

* imports
* function calls (if detectable)
* service → repository relationships

Format:

```json
{
  "src/leads/lead_service.py": [
    "src/leads/lead_repository.py",
    "src/common/email_validator.py"
  ]
}
```

---

## 🧠 4. summaries.json (VERY IMPORTANT)

Generate concise semantic summaries for:

* each file
* each module

Summaries must capture intent, not just structure.

Format:

```json
{
  "src/leads/lead_service.py": "Handles creation, validation, and lifecycle management of CRM leads.",
  "module:leads": "Lead management module responsible for capturing, assigning, and converting leads."
}
```

---

## 📄 5. files.json (OPTIONAL)

Include metadata:

```json
{
  "src/leads/lead_service.py": {
    "language": "python",
    "module": "leads",
    "size": 1200
  }
}
```

---

## ⚙️ EXTRA REQUIREMENTS

1. Prefer semantic understanding over raw syntax.
2. Use function/class boundaries for indexing (NOT arbitrary chunks).
3. Include line numbers for all symbols.
4. Ensure consistency across all JSON files.
5. Avoid duplication of symbols.
6. Handle large repos efficiently (assume incremental indexing is needed).

---

## 🚀 ADVANCED BEHAVIOR (IMPORTANT)

Simulate modern 2026 techniques:

* Generate summaries FIRST, then structure around them (Meta-RAG)
* Infer high-level relationships (e.g., "auth middleware used by routes")
* Build a lightweight knowledge graph via dependencies
* Prefer meaningful grouping over directory-only grouping

---

## 📌 TASK

Given the provided codebase or file input, generate all AI index files.

If the codebase is large:

* Process it module-by-module
* Ensure output is scalable and consistent

Return ONLY valid JSON outputs for each file.
