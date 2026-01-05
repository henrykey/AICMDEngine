# Claude Code Diagnostic Prompt: Membership Service Deletion Bug

## Purpose

Use this prompt with Claude Code (`/claude-code`) to investigate why Membership Service DELETE operations return success (HTTP 204) but don't actually delete users from the database.

## Prompt to Run

```
Investigate and fix the Membership Service user deletion data consistency bug.

## Problem
The DELETE /v2/members/{id} endpoint returns HTTP 204 (success) but doesn't actually delete the user from the database. The user still appears in GET /v2/members after deletion.

## Your Task
1. Locate the Membership Service user deletion endpoint handler
2. Trace through the deletion logic from API handler → database operation
3. Identify why deletion succeeds (HTTP 204) but user remains in database
4. Check for:
   - Transaction rollback issues
   - Soft-delete logic vs hard delete
   - Exception handling that silently catches deletion errors
   - Cascade delete problems
   - Conditional logic that skips deletion

5. Provide a diagnostic report showing:
   - Root cause of the issue
   - Whether it's a transaction issue, missing delete operation, or logical error
   - Code locations that need fixing

## Success Criteria
- Identify the exact code causing the issue
- Explain why HTTP 204 is returned even though deletion fails
- Provide recommendations for fixing the issue

Use the investigation checklist in MEMBERSHIP_DELETE_ISSUE.md as your guide.
```

## Expected Output

Claude Code should return something like:

```
Root cause: DELETE handler implements SOFT DELETE, not HARD DELETE
- Calls deactivateMember() which sets status='inactive'
- Returns 204 immediately without actual deletion
- GET /v2/members has no status filter, returns all users

Code locations:
- MembersApiController.java:199 - Delete handler
- MemberService.java:231-268 - Deactivate method
- MemberRepository.java:186-228 - List queries without filter

Recommendations:
Option A: Implement true hard delete
Option B: Filter out inactive from GET responses
```

## Key Documents

After diagnosis, consult:
- `MEMBERSHIP_DELETE_ROOT_CAUSE.md` - Detailed analysis and fix options
- `EXECUTION_ENGINE_FIXES_SUMMARY.md` - How the execution engine integrates
- `MEMBERSHIP_DELETE_ISSUE.md` - Original problem statement

## Test Reproduction

```bash
# 1. Create test user
curl -X POST http://localhost:8080/v2/members \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser_bug","email":"test@example.com"}'
# Get user ID from response (e.g., 42)

# 2. Verify user exists
curl -X GET http://localhost:8080/v2/members \
  -H "Authorization: Bearer <token>" | grep testuser_bug
# Should find it

# 3. Delete user
curl -X DELETE http://localhost:8080/v2/members/42 \
  -H "Authorization: Bearer <token>"
# Returns 204 ✅

# 4. Check if user still exists
curl -X GET http://localhost:8080/v2/members \
  -H "Authorization: Bearer <token>" | grep testuser_bug
# BUG: User still found! ❌
```

## Impact on AICMDEngine

- Our backend: ✅ Working correctly
- Issue location: ❌ Membership Service soft-delete behavior
- Required action: Fix Membership Service, not AICMDEngine
