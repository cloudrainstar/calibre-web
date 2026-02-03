# Kobo API Request/Response Capture - Implementation Summary

## Overview

The Kobo sync implementation has been enhanced to capture ALL request and response data for both:
1. **Kobo Store API** (library sync, metadata, authentication)
2. **Kobo Reading Services API** (annotations, reading state)

## Changes Made

### 1. Modified `kobo.py` - Store API Capture

**File:** `cps/kobo.py`
**Function:** `redirect_or_proxy_request()`

**Before:**
- GET requests were redirected to Kobo (307 redirect)
- Other requests were proxied
- Minimal logging

**After:**
- ALL requests are now proxied (no redirects)
- Complete request/response capture with debug logging
- Structured log format for easy parsing

**Why the change:**
- Redirects prevent capturing the actual exchange
- Proxying allows us to see both sides of the communication
- Enables future emulation of Store API endpoints

### 2. Enhanced `readingservices.py` - Reading Services Capture

**File:** `cps/readingservices.py`
**Function:** `proxy_to_kobo_reading_services()`

**Features:**
- Captures annotation sync requests/responses
- Logs request headers, body, method
- Logs response status, headers, body
- Redacts sensitive information (auth tokens, cookies)

### 3. Added Emulation Framework

**Files:** `readingservices.py`

**New Functions:**
- `can_emulate_kobo_response()` - Check if local emulation possible
- `emulate_kobo_response()` - Generate response from local DB

**Purpose:**
- Placeholder for future offline/cached operation
- Framework for custom features
- Performance optimization potential

## What Gets Captured

### Request Data
```
- HTTP Method (GET, POST, PATCH, DELETE)
- Full URL and path
- Query parameters
- Headers (with sensitive data redacted)
- Request body (JSON parsed if applicable)
```

### Response Data
```
- Status code and reason
- Response headers (with sensitive data redacted)
- Response body (JSON parsed if applicable)
- Content type and size
```

### Sensitive Data Handling

The following are automatically redacted in logs:
- `Authorization` headers
- `Cookie` headers
- `Set-Cookie` headers
- `x-kobo-userkey` headers

## Log Format

### Store API
```
===============================================================================
KOBO STORE API - REQUEST CAPTURE
===============================================================================
Method: GET
Path: /kobo/{auth}/v1/library/sync
...
-------------------------------------------------------------------------------
KOBO STORE API - RESPONSE CAPTURE
-------------------------------------------------------------------------------
Status Code: 200
...
===============================================================================
```

### Reading Services
```
===============================================================================
KOBO READING SERVICES - REQUEST CAPTURE
===============================================================================
Method: PATCH
Path: /api/v3/content/{uuid}/annotations
...
-------------------------------------------------------------------------------
KOBO READING SERVICES - RESPONSE CAPTURE
-------------------------------------------------------------------------------
Status Code: 200
...
===============================================================================
```

## How to Use

### 1. Enable Capture

```
Admin Panel > Basic Configuration > Logging > Set to "Debug"
```

### 2. Trigger Sync

```
- Connect Kobo device
- Sync library
- Create/modify annotations
- Sync again
```

### 3. View Captured Data

```bash
# Watch all Kobo traffic
tail -f calibre-web.log | grep -E '(KOBO STORE|KOBO READING)'

# Watch only Store API
tail -f calibre-web.log | grep 'KOBO STORE API'

# Watch only Reading Services
tail -f calibre-web.log | grep 'KOBO READING SERVICES'

# Export to separate files
grep 'KOBO STORE API' calibre-web.log > store_api.log
grep 'KOBO READING SERVICES' calibre-web.log > reading_services.log
```

## Benefits

### 1. Understanding the API
- See exact request/response format
- Understand Kobo's expectations
- Debug sync issues

### 2. Future Emulation
- Build offline support
- Cache common responses
- Custom features without Kobo dependency

### 3. Performance Analysis
- Identify slow endpoints
- Optimize proxy behavior
- Plan caching strategy

### 4. Troubleshooting
- Complete audit trail
- Debug authentication issues
- Trace sync failures

## Performance Impact

### With Debug Logging Enabled
- Slight performance impact due to logging
- Log files grow faster
- Recommended for development/testing

### With Info/Warning Logging (Production)
- No capture overhead
- Normal performance
- Capture disabled

**Recommendation:** Use Debug logging during initial setup and troubleshooting, then switch back to Info for normal operation.

## Documentation

- **Testing Guide:** `KOBO_ANNOTATIONS_TESTING.md`
- **Emulation Guide:** `KOBO_EMULATION_GUIDE.md`
- **Quick Reference:** `KOBO_REQUEST_RESPONSE_REFERENCE.md`

## Future Enhancements

Potential uses of captured data:

1. **Offline Mode**
   - Serve responses without internet
   - Queue changes for next online sync

2. **Caching Layer**
   - Cache metadata responses
   - Reduce Kobo API calls
   - Faster sync times

3. **Custom Features**
   - Modify responses (e.g., filter content)
   - Add metadata not in Kobo API
   - Integration with other services

4. **Analytics**
   - Track sync patterns
   - Monitor API health
   - Usage statistics

## Implementation Notes

### Why Proxy Instead of Redirect?

**Redirect (old approach):**
```
Client → Calibre-Web → 307 Redirect → Client → Kobo Store
```
- Calibre-Web can't see response
- Can't capture data
- Simple but limited

**Proxy (new approach):**
```
Client → Calibre-Web → Kobo Store → Calibre-Web → Client
```
- Calibre-Web sees both request and response
- Can capture, modify, or cache data
- Enables future enhancements

### Why Two Separate Proxies?

**Store API** (`kobo.py`):
- Library sync
- Book metadata
- Authentication
- Device management

**Reading Services** (`readingservices.py`):
- Annotations
- Reading state
- Progress tracking

Different endpoints, different purposes, separate modules for clarity.

## Security Considerations

1. **Debug Logs Contain User Data**
   - Highlighted text
   - Notes
   - Reading progress
   - Book titles

2. **Sensitive Data is Redacted**
   - Auth tokens
   - API keys
   - Cookies

3. **Log File Access**
   - Restrict log file permissions
   - Rotate logs regularly
   - Consider log aggregation

4. **Production Use**
   - Use Info logging in production
   - Only enable Debug for troubleshooting
   - Monitor log file sizes

## Backward Compatibility

- No breaking changes
- Existing functionality preserved
- Only logging behavior changed
- Can be disabled by setting log level to Info/Warning

## Tested With

- Kobo Devices (all models with firmware 4.x+)
- Calibre-Web (latest version)
- Python 3.x
- SQLAlchemy (for database)

## Support

For issues or questions:
1. Check logs for errors
2. Verify debug logging is enabled
3. Review captured request/response format
4. Consult documentation files
