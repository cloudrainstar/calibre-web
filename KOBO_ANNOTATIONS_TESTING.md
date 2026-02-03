# Kobo Annotations Testing Guide

This guide will help you test the new Kobo annotation storage feature.

## Prerequisites

1. A Kobo e-reader device
2. Calibre-Web with Kobo sync enabled
3. At least one book synced to your Kobo device

## Setup

1. **Enable Kobo Sync**
   - Go to Admin > Basic Configuration > Feature Configuration
   - Enable "Kobo Sync"
   - Save changes

2. **Register Your Kobo Device**
   - Follow the standard Kobo setup process in Calibre-Web
   - Note: Your device should already be registered if you've used Kobo sync before

## Testing Procedure

### Test 1: Create Annotations

1. **On your Kobo device:**
   - Open a book that's synced from Calibre-Web
   - Highlight some text
   - Add a note to the highlight (optional)
   - Create 2-3 different highlights/notes in different locations

2. **Sync the device:**
   - Connect to WiFi and ensure the device syncs
   - OR connect via USB and trigger sync manually

3. **Verify in database:**
   ```bash
   sqlite3 /path/to/calibre-web/app.db
   
   -- Check if annotations were stored
   SELECT * FROM kobo_annotation;
   
   -- Check sync tracking
   SELECT * FROM kobo_annotation_sync;
   ```

4. **Expected results:**
   - You should see records in both tables
   - `kobo_annotation` should contain:
     - highlighted_text (the text you selected)
     - note_text (if you added a note)
     - progress_percent (calculated position in book)
     - chapter_filename (the chapter where annotation was made)
   - `kobo_annotation_sync` should have matching annotation_id entries

### Test 2: Update Annotations

1. **On your Kobo device:**
   - Find an existing highlight
   - Edit its note (add or change text)

2. **Sync the device**

3. **Verify in database:**
   ```sql
   SELECT annotation_id, highlighted_text, note_text, last_modified 
   FROM kobo_annotation 
   ORDER BY last_modified DESC;
   ```

4. **Expected results:**
   - The annotation record should be updated
   - `last_modified` timestamp should be recent
   - The note_text should reflect your changes

### Test 3: Delete Annotations

1. **On your Kobo device:**
   - Delete one of your highlights

2. **Sync the device**

3. **Verify in database:**
   ```sql
   SELECT COUNT(*) FROM kobo_annotation;
   SELECT COUNT(*) FROM kobo_annotation_sync;
   ```

4. **Expected results:**
   - The annotation should be removed from both tables
   - Counts should decrease by 1

### Test 4: Multiple Books

1. **Create annotations in 2-3 different books**
2. **Sync the device**
3. **Verify in database:**
   ```sql
   SELECT book_id, COUNT(*) as annotation_count
   FROM kobo_annotation
   GROUP BY book_id;
   ```

4. **Expected results:**
   - You should see annotation counts for each book
   - Each book should have the correct number of annotations

### Test 5: Progress Calculation

1. **Create annotations at different locations in a book:**
   - Beginning (chapter 1)
   - Middle (halfway through)
   - End (near the last chapter)

2. **Sync and check database:**
   ```sql
   SELECT 
       highlighted_text,
       chapter_filename,
       chapter_progress,
       progress_percent
   FROM kobo_annotation
   ORDER BY progress_percent;
   ```

3. **Expected results:**
   - progress_percent should increase from beginning to end
   - Values should be between 0 and 100
   - Annotations should be ordered logically by book position

## Troubleshooting

### Annotations Not Appearing

1. **Check Calibre-Web logs:**
   ```bash
   tail -f /path/to/calibre-web.log | grep -i annotation
   ```

2. **Verify Kobo sync is enabled:**
   - Admin panel > Basic Configuration
   - Check "Kobo Sync" is enabled

3. **Check reading services host:**
   - Look for "reading_services_host" in Kobo init response
   - It should point to your Calibre-Web URL, not Kobo's servers

### Database Errors

1. **Check table creation:**
   ```sql
   .schema kobo_annotation
   .schema kobo_annotation_sync
   ```
   
2. **Verify tables exist and have correct structure**

3. **Check for migration errors in logs**

### Sync Issues

1. **Verify network connectivity** between Kobo device and Calibre-Web

2. **Check authentication** - ensure user is logged in

3. **Review proxy settings** - if using reverse proxy, ensure paths are correct

## Viewing Annotations

To view all annotations for a specific user:

```sql
SELECT 
    ka.book_id,
    ka.annotation_type,
    ka.highlighted_text,
    ka.note_text,
    ka.progress_percent,
    ka.created,
    ka.last_modified
FROM kobo_annotation ka
WHERE ka.user_id = YOUR_USER_ID
ORDER BY ka.book_id, ka.progress_percent;
```

To get annotation statistics:

```sql
SELECT 
    COUNT(*) as total_annotations,
    COUNT(DISTINCT book_id) as books_with_annotations,
    AVG(progress_percent) as avg_progress
FROM kobo_annotation
WHERE user_id = YOUR_USER_ID;
```

## Capturing Request/Response for Emulation

The reading services proxy captures all request and response data when log level is set to DEBUG. This allows you to:

1. **Understand Kobo's API structure** for potential offline operation
2. **Build cached/emulated responses** for books in your database
3. **Debug annotation sync issues**

### Enable Debug Logging

1. Go to Admin > Basic Configuration > Logging
2. Set "Log Level" to "Debug"
3. Save changes

### View Captured Data

Check your Calibre-Web log file for entries like:

```
===============================================================================
KOBO READING SERVICES - REQUEST CAPTURE
===============================================================================
Method: PATCH
Path: /api/v3/content/abc-123-def/annotations
...
Request Body (JSON):
{
  "updatedAnnotations": [...],
  "deletedAnnotationIds": [...]
}
-------------------------------------------------------------------------------
KOBO READING SERVICES - RESPONSE CAPTURE
-------------------------------------------------------------------------------
Status Code: 200
Response Body (JSON):
...
===============================================================================
```

### Use Cases for Captured Data

**Offline Mode**: Use captured responses to serve annotation requests without internet
**Performance**: Cache common responses to reduce latency
**Development**: Understand Kobo's exact API requirements for custom features

## Advanced: API Testing

You can test the API directly using curl:

```bash
# Get auth token from your Kobo device setup
AUTH_TOKEN="your-kobo-auth-token"
BOOK_UUID="book-uuid-here"

# Test annotation retrieval (should proxy to Kobo)
curl -X GET "http://localhost:8083/api/v3/content/${BOOK_UUID}/annotations" \
  -H "Authorization: Bearer ${AUTH_TOKEN}"

# Note: PATCH requests require valid Kobo device headers
# It's easier to test through actual device sync
```

## Success Criteria

Your implementation is working correctly if:

1. ✅ Annotations created on Kobo appear in `kobo_annotation` table
2. ✅ Annotations can be updated and changes are reflected
3. ✅ Deleted annotations are removed from database
4. ✅ Progress calculations are reasonable (0-100%)
5. ✅ Multiple books can have annotations stored separately
6. ✅ Sync tracking prevents duplicate entries
7. ✅ No errors in Calibre-Web logs during sync

## Notes

- Annotations are stored locally in your Calibre-Web database
- They are NOT synced to Kobo's cloud (by design)
- Each user's annotations are separate (user_id field)
- The feature requires Kobo sync to be enabled
- Annotations will still be sent to Kobo's servers (proxied)
