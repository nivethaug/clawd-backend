# Backend Build and Publish

> [TOC](toc.md) | Updated: 2026-07-12

## Endpoint

`POST /projects/{project_id}/publish/backend`

Builds and publishes the backend for a project by running the project's `backend/buildpublish.py`.

## Auth

Requires `Authorization: Bearer <token>` and project ownership.

## Request

```json
{
  "project_path": null,
  "project_name": null,
  "skip_install": false,
  "skip_build": false,
  "restart": true
}
```

| Field | Type | Description |
| --- | --- | --- |
| `project_path` | string/null | Optional override. Defaults to `projects.project_path`. |
| `project_name` | string/null | Optional PM2/project name override. Defaults to database project name. |
| `skip_install` | boolean | Adds `--skip-install` to `buildpublish.py`. |
| `skip_build` | boolean | Adds `--skip-build` to `buildpublish.py`. |
| `restart` | boolean | Adds `--restart` when true. |

## Behavior

1. Validates project ownership.
2. Loads project metadata from the database.
3. Resolves `{project_path}/backend`.
4. Requires `buildpublish.py`.
5. Runs `python3 buildpublish.py` in the backend directory.
6. Returns a trimmed stdout/stderr response.

Timeout is 15 minutes.

## Response

```json
{
  "success": true,
  "message": "Backend build and publish completed successfully",
  "output": "...",
  "error": null
}
```

Failure response uses the same response model with `success=false`.

## Related

- [publish_frontend.md](./publish_frontend.md)
- [project_creation.md](./project_creation.md)
