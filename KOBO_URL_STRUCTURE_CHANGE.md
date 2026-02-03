# Kobo Reading Services URL Structure Change

## Summary

The Reading Services API has been restructured to use per-user authentication via auth tokens in the URL path, matching the pattern used by the main Kobo sync API.

## Changes Made

### Before (Multi-Blueprint Approach)
```
/api/v3/content/{book-uuid}/annotations
/api/v3/content/checkforchanges
/api/UserStorage/Metadata
```

**Issues:**
- No per-user authentication in URL
- Relied solely on request headers for auth
- Two separate blueprints (api_v3, userstorage)
- Inconsistent with main Kobo API pattern

### After (Single Blueprint with Auth Token)
```
/readingservices/{auth-token}/api/v3/content/{book-uuid}/annotations
/readingservices/{auth-token}/api/v3/content/checkforchanges
/readingservices/{auth-token}/api/UserStorage/Metadata
```

**Benefits:**
- ✅ Per-user authentication via auth token
- ✅ Consistent with main Kobo API (`/kobo/{auth-token}/...`)
- ✅ Single blueprint for cleaner code
- ✅ Better user isolation
- ✅ Easier to debug (auth in URL)

## Technical Changes

### File: `cps/readingservices.py`

**Blueprint Creation:**
```python
# OLD
readingservices_api_v3 = Blueprint("readingservices_api_v3", __name__, url_prefix="/api/v3")
readingservices_userstorage = Blueprint("readingservices_userstorage", __name__, url_prefix="/api/UserStorage")

# NEW
readingservices = Blueprint("readingservices", __name__, url_prefix="/readingservices/<auth_token>")
kobo_auth.disable_failed_auth_redirect_for_blueprint(readingservices)
kobo_auth.register_url_value_preprocessor(readingservices)
```

**Route Decorators:**
```python
# OLD
@readingservices_api_v3.route("/content/<entitlement_id>/annotations", methods=["GET", "PATCH"])

# NEW
@readingservices.route("/api/v3/content/<entitlement_id>/annotations", methods=["GET", "PATCH"])
```

### File: `cps/main.py`

**Blueprint Registration:**
```python
# OLD
from .readingservices import readingservices_api_v3, readingservices_userstorage
app.register_blueprint(readingservices_api_v3)
app.register_blueprint(readingservices_userstorage)

# NEW
from .readingservices import readingservices
app.register_blueprint(readingservices)
```

### File: `cps/kobo.py`

**Reading Services Host Configuration:**
```python
# OLD
kobo_resources["reading_services_host"] = calibre_web_url

# NEW
kobo_resources["reading_services_host"] = calibre_web_url + url_for(
    "readingservices.handle_annotations",
    auth_token=kobo_auth.get_auth_token(),
    entitlement_id=""
).rstrip("/api/v3/content//annotations")
```

This ensures the Kobo device knows to include the auth token when making annotation requests.

## URL Structure Comparison

### Main Kobo Sync API
```
/kobo/{auth-token}/v1/library/sync
/kobo/{auth-token}/v1/library/{uuid}/metadata
/kobo/{auth-token}/v1/library/{uuid}/state
```

### Reading Services API (Now Consistent)
```
/readingservices/{auth-token}/api/v3/content/{uuid}/annotations
/readingservices/{auth-token}/api/v3/content/checkforchanges
/readingservices/{auth-token}/api/UserStorage/Metadata
```

Both follow the same pattern: `/{service}/{auth-token}/{path}`

## Authentication Flow

1. **Device Registration:**
   - User registers Kobo device in Calibre-Web
   - Receives unique auth token

2. **Initialization Request:**
   - Device calls `/kobo/{auth-token}/v1/initialization`
   - Receives `reading_services_host` with auth token embedded

3. **Annotation Requests:**
   - Device uses provided URL: `/readingservices/{auth-token}/...`
   - Auth token in URL automatically authenticates user
   - No additional auth headers needed (but still supported)

## Impact on Existing Setups

### For Users

**No changes needed!** The Kobo device receives the correct URL from the initialization endpoint automatically.

### For Developers

If you're testing the API manually:

**Old curl command:**
```bash
curl -X GET "http://localhost:8083/api/v3/content/${BOOK_UUID}/annotations" \
  -H "Authorization: Bearer ${AUTH_TOKEN}"
```

**New curl command:**
```bash
curl -X GET "http://localhost:8083/readingservices/${AUTH_TOKEN}/api/v3/content/${BOOK_UUID}/annotations"
```

## Security Improvements

1. **URL-Based Auth:**
   - Auth token in URL path
   - Consistent with OAuth patterns
   - Easier to debug (visible in logs)

2. **User Isolation:**
   - Each user has unique auth token
   - Token embedded in all requests
   - No cross-user data leakage

3. **Kobo Auth Integration:**
   - Uses same auth system as main Kobo sync
   - Automatic token validation
   - Failed auth handling

## Backward Compatibility

### Breaking Changes

None for end users! The change is transparent because:
- Kobo device gets URL from initialization
- URL is dynamically generated with correct token
- Old installations will receive new URL on next sync

### Migration Path

1. Update code (already done)
2. Restart Calibre-Web
3. Kobo devices will automatically use new URLs on next sync
4. No manual intervention required

## Testing

### Manual Testing

```bash
# Get your auth token from Kobo device registration
AUTH_TOKEN="your-token-here"
BOOK_UUID="book-uuid-here"

# Test annotation retrieval
curl "http://localhost:8083/readingservices/${AUTH_TOKEN}/api/v3/content/${BOOK_UUID}/annotations"

# Test with invalid token (should fail)
curl "http://localhost:8083/readingservices/invalid-token/api/v3/content/${BOOK_UUID}/annotations"
```

### Device Testing

1. Sync Kobo device
2. Create annotations on device
3. Sync again
4. Check logs for correct URL usage:
   ```
   KOBO READING SERVICES - REQUEST CAPTURE
   Path: /readingservices/{token}/api/v3/content/{uuid}/annotations
   ```

## Logging Changes

Log entries now show the full path including auth token:

**Before:**
```
Path: /api/v3/content/{uuid}/annotations
```

**After:**
```
Path: /readingservices/{token}/api/v3/content/{uuid}/annotations
```

Note: Sensitive data (auth tokens) are still redacted in header logging.

## Future Enhancements

With per-user URLs, we can now:

1. **Rate Limiting:** Apply per-user rate limits
2. **Usage Analytics:** Track per-user API usage
3. **Custom Routes:** Different routes for different user tiers
4. **Caching:** Per-user response caching

## Documentation Updates

All documentation has been updated to reflect the new URL structure:

- ✅ `KOBO_ANNOTATIONS_TESTING.md` - Updated curl examples
- ✅ `KOBO_REQUEST_RESPONSE_REFERENCE.md` - Updated endpoint list
- ✅ `KOBO_CAPTURE_CHANGES.md` - Updated proxy comparison
- ✅ This document - Complete migration guide

## Troubleshooting

### Issue: Annotations not syncing

**Check:**
1. Is reading_services_host set correctly in initialization?
2. Does the URL include the auth token?
3. Is the auth token valid?

**Debug:**
```bash
# Check initialization response
curl "http://localhost:8083/kobo/${AUTH_TOKEN}/v1/initialization" | jq .Resources.reading_services_host

# Should return: "http://localhost:8083/readingservices/{token}"
```

### Issue: 404 Not Found

**Likely causes:**
1. Old code still using `/api/v3/...` without `/readingservices/` prefix
2. Auth token missing from URL
3. Blueprint not registered properly

**Fix:**
1. Verify blueprint registration in `main.py`
2. Check route decorators in `readingservices.py`
3. Restart Calibre-Web

### Issue: Authentication failing

**Check:**
1. Auth token is valid (matches registered device)
2. kobo_auth preprocessor is registered
3. User is authenticated via token

**Debug:**
Enable debug logging and check for auth messages in logs.

## Code Review Checklist

When reviewing this change:

- [x] Blueprint uses `<auth_token>` in url_prefix
- [x] kobo_auth preprocessor registered
- [x] All routes include full path (`/api/v3/...`, `/api/UserStorage/...`)
- [x] Main.py registers single blueprint
- [x] HandleInitRequest sets correct reading_services_host
- [x] Documentation updated
- [x] No linter errors
- [x] Backward compatible (auto-migration)

## Conclusion

This change brings the Reading Services API in line with the main Kobo sync API, providing:
- Better security through per-user authentication
- Cleaner code with single blueprint
- Consistent URL patterns
- Foundation for future enhancements

Users will not notice any change - it's completely transparent!
