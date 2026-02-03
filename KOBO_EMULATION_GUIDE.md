# Kobo Reading Services Emulation Guide

This guide explains how to use the captured request/response data to build emulated responses for offline or enhanced operation.

## Overview

The `readingservices.py` module captures all communication between your Kobo device and Kobo's Reading Services API. This data can be used to:

1. **Understand the API structure** - See exactly what Kobo expects
2. **Build offline support** - Serve responses without internet connection
3. **Enhance performance** - Cache common responses
4. **Custom features** - Modify responses based on your needs

## Captured Data Format

### Request Capture
```
Method: GET/PATCH/POST/DELETE
Path: /api/v3/content/{book-uuid}/annotations
Headers: Content-Type, Authorization, etc.
Body: JSON data (for PATCH/POST requests)
```

### Response Capture
```
Status Code: 200, 404, etc.
Headers: Content-Type, Content-Length, etc.
Body: JSON or binary data
```

## How to Capture Data

1. **Enable Debug Logging**
   ```
   Admin > Basic Configuration > Logging > Log Level: Debug
   ```

2. **Sync Your Kobo Device**
   - Create annotations on device
   - Sync with Calibre-Web
   - Review log file for captured data

3. **Extract Captured Data**
   ```bash
   grep -A 50 "KOBO READING SERVICES - REQUEST CAPTURE" calibre-web.log > captured_requests.log
   grep -A 50 "KOBO READING SERVICES - RESPONSE CAPTURE" calibre-web.log > captured_responses.log
   ```

## Common API Patterns

### 1. Annotation Retrieval (GET)

**Request:**
```
GET /api/v3/content/{book-uuid}/annotations
```

**Response:**
```json
{
  "annotations": [
    {
      "id": "annotation-uuid",
      "type": "highlight",
      "highlightedText": "Sample text",
      "location": {
        "span": {
          "chapterFilename": "chapter1.xhtml",
          "chapterProgress": 0.45
        }
      }
    }
  ]
}
```

### 2. Annotation Update (PATCH)

**Request:**
```json
{
  "updatedAnnotations": [
    {
      "id": "annotation-uuid",
      "type": "highlight",
      "highlightedText": "Sample highlighted text",
      "location": { ... }
    }
  ],
  "deletedAnnotationIds": ["old-annotation-uuid"]
}
```

**Response:**
```json
{
  "status": "success"
}
```

## Building Emulated Responses

### Step 1: Analyze Captured Data

Review your captured logs to understand:
- What fields are required vs optional
- Expected data types and formats
- Error response structures

### Step 2: Implement Emulation Function

Edit `cps/readingservices.py`:

```python
def emulate_kobo_response(request_type, entitlement_id=None):
    """Generate emulated response from local database."""
    
    if request_type == 'annotations' and request.method == 'GET':
        # Query local annotations
        book = calibre_db.get_book_by_uuid(entitlement_id)
        if not book:
            return make_response(jsonify({"error": "Book not found"}), 404)
        
        annotations = ub.session.query(ub.KoboAnnotation).filter(
            ub.KoboAnnotation.book_id == book.id,
            ub.KoboAnnotation.user_id == current_user.id
        ).all()
        
        # Format as Kobo expects
        response_data = {
            "annotations": [
                {
                    "id": ann.annotation_id,
                    "type": ann.annotation_type,
                    "highlightedText": ann.highlighted_text,
                    "noteText": ann.note_text,
                    "highlightColor": ann.highlight_color,
                    "location": {
                        "span": {
                            "chapterFilename": ann.chapter_filename,
                            "chapterProgress": ann.chapter_progress
                        }
                    },
                    "clientLastModifiedUtc": ann.last_modified.strftime("%Y-%m-%dT%H:%M:%SZ")
                }
                for ann in annotations
            ]
        }
        
        response = make_response(jsonify(response_data), 200)
        response.headers['Content-Type'] = 'application/json'
        return response
    
    # Fall back to proxy
    return None
```

### Step 3: Enable Emulation

Update the condition check:

```python
def can_emulate_kobo_response(entitlement_id=None):
    """Check if we can serve emulated response."""
    
    # Check if book exists in local database
    if entitlement_id:
        book = calibre_db.get_book_by_uuid(entitlement_id)
        if book:
            # Could add more checks:
            # - User preference for offline mode
            # - Cache freshness
            # - Network availability
            return True
    
    return False
```

### Step 4: Integrate in Handler

```python
@readingservices_api_v3.route("/content/<entitlement_id>/annotations", methods=["GET", "PATCH"])
@requires_reading_services_auth
def handle_annotations(entitlement_id):
    # Try emulation first
    if request.method == "GET" and can_emulate_kobo_response(entitlement_id):
        emulated_response = emulate_kobo_response('annotations', entitlement_id)
        if emulated_response:
            log.info(f"Serving emulated response for {entitlement_id}")
            return emulated_response
    
    # ... rest of function (PATCH handling, proxy)
```

## Use Cases

### Use Case 1: Offline Reading

**Goal:** Allow annotation sync without internet

**Implementation:**
1. Capture all annotation responses during online sync
2. Store response structure in database
3. When offline, generate responses from local data
4. Queue PATCH requests for next online sync

### Use Case 2: Performance Optimization

**Goal:** Reduce latency for annotation retrieval

**Implementation:**
1. Cache Kobo responses with TTL
2. Serve from cache for frequent requests
3. Invalidate cache on PATCH/DELETE
4. Background refresh stale cache

### Use Case 3: Custom Features

**Goal:** Add features not in Kobo's API

**Implementation:**
1. Modify emulated responses to include custom fields
2. Add filtering/sorting not available in Kobo API
3. Integrate with other services (e.g., export to Notion)

## Testing Emulated Responses

1. **Enable emulation** in code
2. **Disable internet** on Calibre-Web server (optional)
3. **Sync Kobo device**
4. **Verify annotations** work as expected
5. **Check logs** for "Serving emulated response" messages

## Comparison: Proxy vs Emulation

| Feature | Proxy | Emulation |
|---------|-------|-----------|
| **Internet Required** | Yes | No |
| **Latency** | Higher | Lower |
| **Customization** | None | Full |
| **Maintenance** | None | Track API changes |
| **Data Privacy** | Sent to Kobo | Stays local |

## Best Practices

1. **Start with Proxy** - Capture real data first
2. **Incremental Emulation** - Implement one endpoint at a time
3. **Fallback Logic** - Always have proxy as fallback
4. **Version Tracking** - Log Kobo API version in responses
5. **Error Handling** - Match Kobo's error formats exactly
6. **Testing** - Test with multiple books and users

## Security Considerations

- **Validate Input** - Even emulated responses should validate entitlement
- **User Isolation** - Ensure users only see their annotations
- **Rate Limiting** - Apply same limits as proxied requests
- **Logging** - Log emulated responses for debugging

## Future Enhancements

Potential improvements to the emulation system:

1. **Database Storage** - Store captured responses in DB
2. **Response Templates** - Define templates for common responses
3. **Smart Caching** - Cache with intelligent invalidation
4. **Metrics** - Track emulation hit rate
5. **Admin UI** - Configure emulation settings
6. **Sync Queue** - Queue offline changes for online sync

## Troubleshooting

### Emulated Response Rejected by Device

- Compare with captured real response
- Check all required fields are present
- Verify data types match exactly
- Check headers (Content-Type, etc.)

### Performance Issues

- Add database indexes for annotation queries
- Implement response caching
- Use batch loading for multiple books

### Data Inconsistency

- Always proxy DELETE operations
- Sync with Kobo periodically
- Implement conflict resolution
- Keep audit log of emulated responses

## Resources

- Captured request/response logs
- Database schema in `cps/ub.py`
- Implementation in `cps/readingservices.py`
- Testing guide in `KOBO_ANNOTATIONS_TESTING.md`

## Example: Complete Emulation Flow

```python
# 1. User requests annotations on Kobo device
# 2. Request arrives at Calibre-Web
# 3. Check if emulation is possible
if can_emulate_kobo_response(book_uuid):
    # 4. Query local database
    annotations = get_local_annotations(book_uuid, user_id)
    
    # 5. Format response
    response = format_as_kobo_expects(annotations)
    
    # 6. Add appropriate headers
    response.headers['Content-Type'] = 'application/json'
    response.headers['X-Served-By'] = 'calibre-web-emulation'
    
    # 7. Return to device
    return response
else:
    # 8. Fallback to proxy
    return proxy_to_kobo_reading_services()
```

This emulation system gives you full control over the annotation experience while maintaining compatibility with Kobo devices.
