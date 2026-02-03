#!/usr/bin/env python
# -*- coding: utf-8 -*-

#  This file is part of the Calibre-Web (https://github.com/janeczku/calibre-web)
#    Copyright (C) 2024 OzzieIsaacs
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <http://www.gnu.org/licenses/>.

"""
Reading Services API for Kobo Annotations/Highlights
Handles annotation sync from Kobo devices

These routes are at the root level: /api/v3/..., /api/UserStorage/...
"""

import json
import os
from datetime import datetime, timezone
from functools import wraps
from flask import Blueprint, request, make_response, jsonify, abort
from werkzeug.datastructures import Headers
import requests

from . import logger, calibre_db, db, config, ub, csrf, kobo_auth
from .cw_login import current_user

log = logger.create()

# Create blueprint to handle the relevant reading services API routes
# Uses auth token in URL like main Kobo blueprint for per-user authentication
readingservices = Blueprint("readingservices", __name__, url_prefix="/readingservices/<auth_token>")
kobo_auth.disable_failed_auth_redirect_for_blueprint(readingservices)
kobo_auth.register_url_value_preprocessor(readingservices)

KOBO_READING_SERVICES_URL = "https://readingservices.kobo.com"

CONNECTION_SPECIFIC_HEADERS = [
    "connection",
    "content-encoding",
    "content-length",
    "transfer-encoding",
]


def proxy_to_kobo_reading_services():
    """
    Proxy the request to Kobo's reading services API.
    """
    try:
        kobo_url = KOBO_READING_SERVICES_URL + request.path
        if request.query_string:
            kobo_url += "?" + request.query_string.decode('utf-8')
        
        log.debug(f"Proxying {request.method} to Kobo Reading Services: {kobo_url}")
        
        # Get request body
        request_body = request.get_data()
        
        # Forward headers (including Authorization, x-kobo-userkey, etc.)
        outgoing_headers = Headers(request.headers)
        outgoing_headers.remove("Host")
        # Remove session cookie - Kobo doesn't need it
        outgoing_headers.pop("Cookie", None)
        
        readingservices_response = requests.request(
            method=request.method,
            url=kobo_url,
            headers=outgoing_headers,
            data=request_body,
            allow_redirects=False,
            timeout=(2, 10)
        )
        
        if readingservices_response.status_code >= 400:
            log.warning(f"Kobo Reading Services error {readingservices_response.status_code}")
        
        response_headers = readingservices_response.headers
        for header_key in CONNECTION_SPECIFIC_HEADERS:
            response_headers.pop(header_key, default=None)
        
        return make_response(
            readingservices_response.content, 
            readingservices_response.status_code, 
            response_headers.items()
        )
    except requests.exceptions.Timeout:
        log.error("Timeout connecting to Kobo Reading Services")
        return make_response(jsonify({"error": "Gateway timeout"}), 504)
    except requests.exceptions.ConnectionError as e:
        log.error(f"Connection error to Kobo Reading Services: {e}")
        return make_response(jsonify({"error": "Bad gateway"}), 502)
    except requests.exceptions.RequestException as e:
        log.error(f"Request failed to Kobo Reading Services: {e}")
        return make_response(jsonify({"error": "Bad gateway"}), 502)
    except Exception as e:
        log.error(f"Unexpected error proxying to Kobo Reading Services: {e}")
        import traceback
        log.error(traceback.format_exc())
        return make_response(jsonify({"error": "Internal server error"}), 500)


def requires_reading_services_auth(f):
    """
    Auth decorator for Reading Services endpoints.
    Checks if Kobo sync is enabled and user is authenticated.
    If not enabled or not authenticated, proxies the request to Kobo without processing.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if Kobo sync is enabled
        if not config.config_kobo_sync:
            log.debug("Kobo sync disabled, proxying to Kobo")
            return proxy_to_kobo_reading_services()
        
        # Check if user is authenticated (cookie from Kobo sync)
        if current_user.is_authenticated:
            return f(*args, **kwargs)
        else:
            # User not authenticated - just proxy to Kobo
            log.debug("Reading services request without auth, proxying to Kobo")
            return proxy_to_kobo_reading_services()
    return decorated_function


def get_book_by_entitlement_id(entitlement_id):
    """Get book from database by UUID (entitlement_id)."""
    try:
        book = calibre_db.get_book_by_uuid(entitlement_id)
        return book
    except Exception as e:
        log.error(f"Error getting book by entitlement ID {entitlement_id}: {e}")
        return None


def log_annotation_data(entitlement_id, method, data=None):
    """Log annotation data and link to book identifiers."""
    log.debug(f"ANNOTATION {method}")
    log.debug(f"Entitlement ID: {entitlement_id}")
    log.debug(f"User: {current_user.name}")
    
    # Try to link to book
    book = get_book_by_entitlement_id(entitlement_id)
    if book:
        log.debug(f"Book: {book.title}")
        log.debug(f"Book ID: {book.id}")
    else:
        log.warning(f"Could not find book for entitlement ID: {entitlement_id}")
    
    if data:
        log.debug("Annotation Data:")
        log.debug(json.dumps(data, indent=2))


# Helper functions for file management
def get_annotation_attachment_dir(entitlement_id):
    """Get the directory path for storing annotation attachments"""
    user_token = kobo_auth.get_auth_token()
    attachment_dir = os.path.join(config.config_calibre_dir, "kobo_annotations", user_token, entitlement_id)
    os.makedirs(attachment_dir, exist_ok=True)
    return attachment_dir


def process_annotation_for_sync(annotation, book, existing_syncs=None):
    """
    Process a single annotation and store in database.
    
    Args:
        annotation: Annotation dict from Kobo
        book: Calibre book object
        existing_syncs: Optional dict of {annotation_id: sync_record} for batch processing
    
    Returns:
        True if stored successfully, False otherwise
    """
    annotation_id = annotation.get('id')
    annotation_type = annotation.get('type', 'highlight')

    # Check if annotation ID exists
    if not annotation_id:
        log.warning("Annotation ID is required for sync")
        return False

    existing_sync = None
    if existing_syncs is not None:
        # Use pre-loaded sync records (batch processing)
        existing_sync = existing_syncs.get(annotation_id)
    else:
        # Fall back to individual query
        existing_sync = ub.session.query(ub.KoboAnnotationSync).filter(
            ub.KoboAnnotationSync.annotation_id == annotation_id,
            ub.KoboAnnotationSync.user_id == current_user.id
        ).first()
    
    # Get existing annotation record
    existing_annotation = ub.session.query(ub.KoboAnnotation).filter(
        ub.KoboAnnotation.annotation_id == annotation_id,
        ub.KoboAnnotation.user_id == current_user.id
    ).first()

    try:
        if existing_annotation:
            # Update existing annotation with full JSON data
            existing_annotation.annotation_type = annotation_type
            existing_annotation.annotation_data = annotation
            existing_annotation.last_modified = datetime.now(timezone.utc)
            log.info(f"Updated annotation {annotation_id} for book {book.id}")
        else:
            # Create new annotation with full JSON data
            new_annotation = ub.KoboAnnotation(
                user_id=current_user.id,
                book_id=book.id,
                annotation_id=annotation_id,
                annotation_type=annotation_type,
                annotation_data=annotation
            )
            ub.session.add(new_annotation)
            log.info(f"Created new annotation {annotation_id} for book {book.id}")
        
        # Update or create sync record
        if existing_sync:
            existing_sync.last_synced = datetime.now(timezone.utc)
        else:
            sync_record = ub.KoboAnnotationSync(
                user_id=current_user.id,
                annotation_id=annotation_id,
                book_id=book.id
            )
            ub.session.add(sync_record)
        
        ub.session_commit()
        return True
        
    except Exception as e:
        log.error(f"Failed to save annotation {annotation_id}: {e}")
        import traceback
        log.error(traceback.format_exc())
        ub.session.rollback()
        return False


@csrf.exempt
@readingservices.route("/api/v3/content/<entitlement_id>/annotations", methods=["GET", "PATCH"])
@requires_reading_services_auth
def handle_annotations(entitlement_id):
    """
    Handle annotation requests for a specific book.
    GET: Retrieve all annotations for a book
    PATCH: Update/create annotations
    """
    # If book is not in our database, proxy to Kobo
    book = get_book_by_entitlement_id(entitlement_id)
    if not book:
        log.warning(f"Book not found for entitlement {entitlement_id}, skipping local sync")
        return proxy_to_kobo_reading_services()

    if request.method == "GET":
        # Return annotations from local database
        # Handle pagination parameters
        limit = request.args.get('limit', type=int, default=100)
        offset = request.args.get('offset', type=int, default=0)
        
        # Query with pagination
        query = ub.session.query(ub.KoboAnnotation).filter(
            ub.KoboAnnotation.book_id == book.id,
            ub.KoboAnnotation.user_id == current_user.id
        ).order_by(ub.KoboAnnotation.last_modified.desc())
        
        # Get total count to check if more pages exist
        total_count = query.count()
        
        # Apply pagination
        annotations = query.offset(offset).limit(limit).all()
        
        annotation_list = []
        for ann in annotations:
            if ann.annotation_data:
                annotation_list.append(ann.annotation_data)
        
        # Calculate next page token if there are more results
        next_offset = offset + limit
        next_page_token = str(next_offset) if next_offset < total_count else None
        
        return jsonify({
            "annotations": annotation_list, 
            "nextPageOffsetToken": next_page_token
        })
    elif request.method == "PATCH":
        try:
            data = request.get_json()
            log_annotation_data(entitlement_id, "PATCH", data)
            
            # Handle deleted annotations
            if data and "deletedAnnotationIds" in data:
                deleted_ids = data["deletedAnnotationIds"]
                log.info(f"Processing {len(deleted_ids)} deleted annotation IDs")
                for annotation_id in deleted_ids:
                    # Delete annotation record
                    ub.session.query(ub.KoboAnnotation).filter(
                        ub.KoboAnnotation.annotation_id == annotation_id,
                        ub.KoboAnnotation.user_id == current_user.id
                    ).delete()
                    
                    # Delete sync record
                    ub.session.query(ub.KoboAnnotationSync).filter(
                        ub.KoboAnnotationSync.annotation_id == annotation_id,
                        ub.KoboAnnotationSync.user_id == current_user.id
                    ).delete()
                    
                    log.info(f"Deleted annotation {annotation_id}")
                
                try:
                    ub.session_commit()
                except Exception as e:
                    log.error(f"Failed to delete annotations: {e}")
                    ub.session.rollback()
            
            # Extract updated annotations
            if data and "updatedAnnotations" in data:
                annotations = data['updatedAnnotations']
                log.info(f"Processing {len(annotations)} updated annotations")
            
                # Batch load existing sync records to avoid N+1 queries
                existing_syncs = {}
                annotation_ids = [a.get('id') for a in annotations if a.get('id')]
                if annotation_ids:
                    syncs = ub.session.query(ub.KoboAnnotationSync).filter(
                        ub.KoboAnnotationSync.annotation_id.in_(annotation_ids),
                        ub.KoboAnnotationSync.user_id == current_user.id
                    ).all()
                    existing_syncs = {s.annotation_id: s for s in syncs}

                for annotation in annotations:
                    process_annotation_for_sync(
                        annotation=annotation, 
                        book=book, 
                        existing_syncs=existing_syncs
                    )

            # All done, return 204 No Content        
            return make_response('', 204)

        except Exception as e:
            log.error(f"Error processing PATCH annotations: {e}")
            import traceback
            log.error(traceback.format_exc())
            return make_response(jsonify({"error": "Internal server error"}), 500)
    else:
        return proxy_to_kobo_reading_services() # Catch-all for other methods


@csrf.exempt
@readingservices.route("/api/v3/content/<entitlement_id>/annotations/<annotation_id>/attachments", methods=["POST", "GET"])
@requires_reading_services_auth
def handle_annotation_attachments(entitlement_id, annotation_id):
    """
    Handle annotation attachment uploads (JPG and SVG files for markup annotations).
    Stores files locally organized by user and book.
    """
    book = get_book_by_entitlement_id(entitlement_id)
    if not book:
        log.warning(f"Book not found for entitlement {entitlement_id}, skipping local sync")
        return proxy_to_kobo_reading_services()
    
    if request.method == "POST":
        # Handle file upload
        if 'attachment' not in request.files:
            return make_response(jsonify({"error": "No file provided"}), 400)
        
        file = request.files['attachment']
        if file.filename == '':
            return make_response(jsonify({"error": "No file selected"}), 400)
        
        # Save file locally
        try:
            attachment_dir = get_annotation_attachment_dir(entitlement_id)
            # Use the original filename which includes the annotation ID
            filepath = os.path.join(attachment_dir, file.filename)
            file.save(filepath)
            log.info(f"Saved annotation attachment: {filepath}")
            
            # Return success response matching Kobo's format
            return make_response(
                jsonify(f"Attachment {file.filename} created."),
                201,
                {"Location": f"/api/v3/content/{entitlement_id}/annotations/{annotation_id}/attachments/{file.filename}"}
            )
        except Exception as e:
            log.error(f"Failed to save attachment: {e}")
            return make_response(jsonify({"error": "Failed to save file"}), 500)
    
    elif request.method == "GET":
        # Serve attachment file
        try:
            # Extract filename from URL (last part of the path)
            filename = request.path.split('/')[-1]
            attachment_dir = get_annotation_attachment_dir(entitlement_id)
            filepath = os.path.join(attachment_dir, filename)
            
            if os.path.exists(filepath):
                from flask import send_file
                return send_file(filepath)
            else:
                return make_response(jsonify({"error": "File not found"}), 404)
        except Exception as e:
            log.error(f"Failed to serve attachment: {e}")
            return make_response(jsonify({"error": "Failed to serve file"}), 500)


@csrf.exempt
@readingservices.route("/api/v3/content/checkforchanges", methods=["POST"])
@requires_reading_services_auth
def handle_check_for_changes():
    """
    Handle check for changes request.
    Should check and remove any ContentId from the request body which are in our database,
    then forward the request to Kobo.
    The request body is like this:
    [
        {
            "ContentId": "2f3dc386-13fb-4589-bab7-5090c4ab27e4",
            "etag": "W/\"0\""
        },
        {
            "ContentId": "c5c0b566-118e-486d-b330-4a614d7498f8",
            "etag": "W/\"0\""
        },
        {
            "ContentId": "23242d62-3b9b-49cf-b9d9-d2677de085c0",
            "etag": "W/\"A:1408092558-7Uhimw6qgE+J7JpyxBiziA, A:1477029255-Iq992+H1kkGYzpOgLXvzNA, C:567181005-J6mRvrCcTUWY4kvt7J1ZUQ, B:1058700540-KkAV6b3EYE+6aKdGXLBjow, A:1406357443-Pjqr2DUG2UOnbnNOYb90pw, B:567634845-SIRCEgIeBEmUAlJyLcZDTg, B:547059529-TXS+v7oQ3Eauqnwo8PUJTg, B:523015816-Xa5fPrXDzUKhZNq2SoHh0g, B:380735-bLnBysoBh0qVtz+R+mCbjw, B:3342957-hrCcbwQ9j0WP3UkHR4s7yw, B:1365732017-iwFphRp+BESQ5b0/k57uiQ, C:1395537364-k/cTsFex1Ui7rkxU+a+IgQ, B:1405634018-oVGhqTo6eUen1tFgQ68Tcg, C:1408244964-vaH5IKpaTkmGrM6vHxI4/A\""
        }
    ]
    """
    # Check and remove any ContentId which are in our database
    content_ids = request.json
    new_content_ids = []
    for item in content_ids:
        content_id = item['ContentId']
        book = get_book_by_entitlement_id(content_id)
        if not book:
            new_content_ids.append(item)

    # Forward the request to Kobo with the new content IDs
    if new_content_ids:
        request.json = new_content_ids
        return proxy_to_kobo_reading_services()
    else:
        # Nothing new, just return 200 with empty json array []
        return make_response(jsonify([]), 200)
    


@csrf.exempt
@readingservices.route("/api/UserStorage/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@requires_reading_services_auth
def handle_user_storage(subpath):
    """
    Handle UserStorage API requests (e.g., /api/UserStorage/Metadata).
    Proxies to Kobo's reading services.
    """
    return proxy_to_kobo_reading_services()


@csrf.exempt
@readingservices.route("/api/v3/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@requires_reading_services_auth
def handle_unknown_reading_service_request(subpath):
    """
    Catch-all handler for any reading services requests not explicitly handled.
    Logs the request and proxies to Kobo's reading services.
    """
    return proxy_to_kobo_reading_services()
