# Kobo Reading Services - Request/Response Quick Reference

This is a quick reference for the captured request/response patterns you'll see in the logs.

## Viewing Captured Data

**Enable Debug Logging:**
```
Admin Panel > Basic Configuration > Logging > Log Level: Debug
```

**Watch logs in real-time:**
```bash
tail -f /path/to/calibre-web.log | grep -A 100 "KOBO READING SERVICES"
```

## Log Output Format

```
================================================================================
KOBO READING SERVICES - REQUEST CAPTURE
================================================================================
Method: [GET|POST|PATCH|DELETE]
Path: /api/v3/content/{uuid}/annotations
Full URL: https://readingservices.kobo.com/api/v3/content/{uuid}/annotations
Query String: [parameters if any]
Request Headers:
  Content-Type: application/json
  Authorization: [REDACTED]
  x-kobo-userkey: [REDACTED]
  User-Agent: ...
Request Body (JSON):
{
  ... request data ...
}
--------------------------------------------------------------------------------
KOBO READING SERVICES - RESPONSE CAPTURE
--------------------------------------------------------------------------------
Status Code: 200
Status Text: OK
Response Headers:
  Content-Type: application/json
  Content-Length: 1234
Response Body (JSON):
{
  ... response data ...
}
================================================================================
```

## Common Endpoints Captured

### 1. Get Annotations
```
GET /readingservices/{auth-token}/api/v3/content/{book-uuid}/annotations
```
**Use:** Retrieve all annotations for a book
**Response:** Array of annotation objects

### 2. Update Annotations
```
PATCH /readingservices/{auth-token}/api/v3/content/{book-uuid}/annotations
```
**Body:** 
```json
{
  "updatedAnnotations": [...],
  "deletedAnnotationIds": [...]
}
```
**Use:** Sync annotation changes from device

### 3. Check for Changes
```
POST /readingservices/{auth-token}/api/v3/content/checkforchanges
```
**Use:** Device checks if server has updates

### 4. UserStorage Requests
```
GET/POST /readingservices/{auth-token}/api/UserStorage/Metadata
```
**Use:** Sync device metadata

**Note:** All Reading Services endpoints now require the user's auth token in the URL path for per-user authentication.

## Annotation Object Structure

From captured responses, typical annotation object:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "highlight",  // or "note"
  "highlightedText": "The text that was highlighted",
  "noteText": "Optional user note",
  "highlightColor": "yellow",  // or "blue", "red", "purple"
  "location": {
    "span": {
      "chapterFilename": "chapter01.xhtml",
      "chapterProgress": 0.45,  // 0.0 to 1.0
      "chapterTitle": "Chapter 1",
      "startChar": 123,
      "endChar": 456,
      "startPath": "/html/body/div/p[3]",
      "endPath": "/html/body/div/p[3]"
    }
  },
  "clientLastModifiedUtc": "2024-01-15T10:30:00Z"
}
```

## PATCH Request Structure

```json
{
  "updatedAnnotations": [
    {
      "id": "new-or-existing-uuid",
      "type": "highlight",
      "highlightedText": "Text content",
      "location": { ... }
    }
  ],
  "deletedAnnotationIds": [
    "uuid-of-deleted-annotation-1",
    "uuid-of-deleted-annotation-2"
  ]
}
```

## Response Status Codes

| Code | Meaning | Action |
|------|---------|--------|
| 200 | Success | Annotations processed |
| 204 | No Content | Success, no response body |
| 400 | Bad Request | Malformed JSON |
| 401 | Unauthorized | Auth token invalid |
| 404 | Not Found | Book not found |
| 500 | Server Error | Kobo service issue |
| 502 | Bad Gateway | Cannot reach Kobo |
| 504 | Gateway Timeout | Kobo service slow |

## Request Headers You'll See

```
Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
x-kobo-userkey: abcd1234-5678-90ef-ghij-klmnopqrstuv
User-Agent: Kobo Touch/4.x.xxxxx
Content-Type: application/json
Accept: application/json
```

## Response Headers You'll See

```
Content-Type: application/json; charset=utf-8
Content-Length: 1234
X-Kobo-RequestId: abc123def456
Date: Mon, 15 Jan 2024 10:30:00 GMT
```

## Extracting Data from Logs

### Get all annotation PATCH requests
```bash
grep -B 5 -A 50 'Method: PATCH' calibre-web.log | grep -A 50 '/annotations'
```

### Get all response bodies
```bash
grep -A 20 'Response Body (JSON)' calibre-web.log
```

### Find errors
```bash
grep -B 10 'Status Code: [4-5]' calibre-web.log
```

### Extract specific book's data
```bash
grep -B 5 -A 50 'book-uuid-here' calibre-web.log
```

## Building Your Emulation

**Step 1:** Capture real data (debug mode)
```
Sync device → Check logs → Extract patterns
```

**Step 2:** Store structure
```python
# Save to reference file or database
annotation_template = {
    "id": "",
    "type": "",
    "highlightedText": "",
    # ... etc
}
```

**Step 3:** Generate from local data
```python
def build_annotation_response(book_uuid):
    annotations = query_local_annotations(book_uuid)
    return format_as_kobo_expects(annotations)
```

**Step 4:** Test
```
Enable emulation → Sync device → Verify → Compare with real
```

## Differences to Watch For

### Field Names
- Kobo uses camelCase (e.g., `highlightedText`)
- Database might use snake_case (e.g., `highlighted_text`)
- **Always convert** when emulating

### Date Formats
- Kobo expects: `2024-01-15T10:30:00Z` (ISO 8601 UTC)
- Python: `datetime.strftime("%Y-%m-%dT%H:%M:%SZ")`

### Progress Values
- Kobo sends: `chapterProgress` as 0.0 to 1.0 (float)
- You might store: percentage 0-100
- **Convert:** `kobo_progress / 100.0` or `db_percent * 100`

## Common Issues in Emulation

### Issue: Device rejects emulated response
**Check:**
- All required fields present?
- Field names exactly match (camelCase)?
- Data types correct (string vs number)?
- Date format is ISO 8601?

### Issue: Annotations duplicated
**Check:**
- Using same UUID for same annotation?
- Sync tracking table updated?
- Checking existing before creating new?

### Issue: Missing annotations
**Check:**
- Query includes correct user_id?
- Book UUID matches exactly?
- Deleted annotations filtered out?

## Performance Notes

**Proxy (default):**
- Latency: 50-200ms (network dependent)
- Always up-to-date
- Requires internet

**Emulated (future):**
- Latency: 5-20ms (database query)
- May be stale if not synced
- Works offline

## Security Checklist

When emulating responses:

- [ ] Verify user owns the book
- [ ] Filter by current_user.id
- [ ] Validate entitlement_id format
- [ ] Sanitize any user input
- [ ] Log emulated requests for audit
- [ ] Apply rate limiting

## Next Steps

1. **Collect Data:** Sync device with debug logging
2. **Analyze Patterns:** Review captured requests/responses
3. **Build Templates:** Create response templates
4. **Implement Emulation:** Code the emulation logic
5. **Test Thoroughly:** Compare emulated vs real responses
6. **Deploy Gradually:** Start with read-only endpoints

## Quick Commands

```bash
# Enable debug mode (in Python/Flask)
export FLASK_DEBUG=1

# Watch for annotation syncs
tail -f calibre-web.log | grep -i annotation

# Count captured requests
grep "REQUEST CAPTURE" calibre-web.log | wc -l

# Export captured data
grep -A 100 "REQUEST CAPTURE" calibre-web.log > requests.json

# Search for specific book
grep "book-uuid" calibre-web.log | less
```

## Documentation References

- **Full Implementation:** `cps/readingservices.py`
- **Database Schema:** `cps/ub.py` (KoboAnnotation, KoboAnnotationSync)
- **Testing Guide:** `KOBO_ANNOTATIONS_TESTING.md`
- **Emulation Guide:** `KOBO_EMULATION_GUIDE.md`
