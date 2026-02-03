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
import zipfile
import re
from datetime import datetime, timezone
from functools import wraps
from flask import Blueprint, request, make_response, jsonify, abort
from werkzeug.datastructures import Headers
import requests
from lxml import etree

from . import logger, calibre_db, db, config, ub, csrf
from .cw_login import current_user

log = logger.create()

# Create blueprints to handle the relevant reading services API routes
readingservices_api_v3 = Blueprint("readingservices_api_v3", __name__, url_prefix="/api/v3")
readingservices_userstorage = Blueprint("readingservices_userstorage", __name__, url_prefix="/api/UserStorage")

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
    
    This function captures both request and response data for debugging and potential
    emulation. The captured data can be used to:
    1. Understand Kobo's API structure
    2. Build offline/cached responses for books in local database
    3. Debug annotation sync issues
    
    To enable detailed capture logging, set log level to DEBUG in Calibre-Web settings.
    """
    try:
        kobo_url = KOBO_READING_SERVICES_URL + request.path
        if request.query_string:
            kobo_url += "?" + request.query_string.decode('utf-8')
        
        log.debug(f"Proxying {request.method} to Kobo Reading Services: {kobo_url}")
        
        # Capture request data for emulation
        request_body = request.get_data()
        log.debug("=" * 80)
        log.debug("KOBO READING SERVICES - REQUEST CAPTURE")
        log.debug("=" * 80)
        log.debug(f"Method: {request.method}")
        log.debug(f"Path: {request.path}")
        log.debug(f"Full URL: {kobo_url}")
        log.debug(f"Query String: {request.query_string.decode('utf-8') if request.query_string else 'None'}")
        
        # Log request headers (redact sensitive info)
        log.debug("Request Headers:")
        for header_name, header_value in request.headers.items():
            if header_name.lower() in ['authorization', 'cookie', 'x-kobo-userkey']:
                log.debug(f"  {header_name}: [REDACTED]")
            else:
                log.debug(f"  {header_name}: {header_value}")
        
        # Log request body
        if request_body:
            try:
                request_json = json.loads(request_body)
                log.debug("Request Body (JSON):")
                log.debug(json.dumps(request_json, indent=2))
            except (json.JSONDecodeError, UnicodeDecodeError):
                log.debug(f"Request Body (Raw, {len(request_body)} bytes):")
                log.debug(request_body[:500])  # First 500 bytes
        else:
            log.debug("Request Body: (empty)")
        
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
        
        # Capture response data for emulation
        log.debug("-" * 80)
        log.debug("KOBO READING SERVICES - RESPONSE CAPTURE")
        log.debug("-" * 80)
        log.debug(f"Status Code: {readingservices_response.status_code}")
        log.debug(f"Status Text: {readingservices_response.reason}")
        
        # Log response headers
        log.debug("Response Headers:")
        for header_name, header_value in readingservices_response.headers.items():
            if header_name.lower() in ['set-cookie']:
                log.debug(f"  {header_name}: [REDACTED]")
            else:
                log.debug(f"  {header_name}: {header_value}")
        
        # Log response body
        response_content = readingservices_response.content
        if response_content:
            content_type = readingservices_response.headers.get('Content-Type', '')
            try:
                if 'application/json' in content_type:
                    response_json = json.loads(response_content)
                    log.debug("Response Body (JSON):")
                    log.debug(json.dumps(response_json, indent=2))
                else:
                    log.debug(f"Response Body ({content_type}, {len(response_content)} bytes):")
                    log.debug(response_content[:500])  # First 500 bytes
            except (json.JSONDecodeError, UnicodeDecodeError):
                log.debug(f"Response Body (Raw, {len(response_content)} bytes):")
                log.debug(response_content[:500])
        else:
            log.debug("Response Body: (empty)")
        
        log.debug("=" * 80)
        
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


def can_emulate_kobo_response(entitlement_id=None):
    """
    Check if we can serve an emulated/cached response instead of proxying to Kobo.
    
    This is a placeholder for future functionality where responses can be:
    - Served from cache for performance
    - Generated locally for offline operation
    - Customized based on local book database
    
    Args:
        entitlement_id: Book UUID to check if we have local data
    
    Returns:
        bool: True if we can emulate the response locally
        
    TODO: Implement logic to:
    1. Check if book exists in local database
    2. Verify we have cached response data
    3. Check if response is still valid/fresh
    """
    # For now, always proxy to Kobo
    # Future implementation could check:
    # - if book.uuid == entitlement_id exists in calibre_db
    # - if we have cached Kobo response data
    # - if user prefers offline mode
    return False


def emulate_kobo_response(request_type, entitlement_id=None):
    """
    Generate an emulated Kobo Reading Services response from local data.
    
    This is a placeholder for future functionality.
    
    Args:
        request_type: Type of request (e.g., 'annotations', 'metadata')
        entitlement_id: Book UUID
        
    Returns:
        Flask response object with emulated data
        
    TODO: Implement based on captured request/response patterns
    """
    # Placeholder - would build response from local database
    # Example for annotations:
    # - Query kobo_annotation table for this book
    # - Format as Kobo expects
    # - Return with appropriate headers
    return make_response(jsonify({"error": "Emulation not yet implemented"}), 501)


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


class EpubProgressCalculator:
    """
    Helper class to calculate progress from EPUB/KEPUB files efficiently.
    Parses the book structure once and reuses it for multiple calculations.
    """
    def __init__(self, book: db.Books):
        self.book = book
        self.spine_items = []
        self.chapter_lengths = []
        self.total_chars = 0
        self.initialized = False
        self.error = False

    def _initialize(self):
        if self.initialized:
            return

        if not self.book or not self.book.path:
            self.error = True
            return

        book_data = None
        kepub_datas = [data for data in self.book.data if data.format.lower() == 'kepub']
        if len(kepub_datas) >= 1:
            book_data = kepub_datas[0]
        else:
            epub_datas = [data for data in self.book.data if data.format.lower() == 'epub']
            if len(epub_datas) >= 1:
                book_data = epub_datas[0]
        
        if not book_data:
            self.error = True
            return

        try:
            file_path = os.path.normpath(os.path.join(
                config.get_book_path(),
                self.book.path,
                book_data.name + "." + book_data.format.lower()
            ))
            
            if not os.path.exists(file_path):
                self.error = True
                return
            
            with zipfile.ZipFile(file_path, 'r') as epub_zip:
                # Find OPF
                container_data = epub_zip.read('META-INF/container.xml')
                container_tree = etree.fromstring(container_data)
                ns = {
                    'container': 'urn:oasis:names:tc:opendocument:xmlns:container',
                    'opf': 'http://www.idpf.org/2007/opf'
                }
                opf_path = container_tree.xpath(
                    '//container:rootfile/@full-path',
                    namespaces={'container': ns['container']}
                )[0]
                
                # Parse OPF
                opf_data = epub_zip.read(opf_path)
                opf_tree = etree.fromstring(opf_data)
                opf_dir = os.path.dirname(opf_path)
                
                # Get manifest
                manifest = {}
                for item in opf_tree.xpath('//opf:manifest/opf:item', namespaces={'opf': ns['opf']}):
                    item_id = item.get('id')
                    href = item.get('href')
                    if item_id and href:
                        full_href = os.path.normpath(os.path.join(opf_dir, href)).replace('\\', '/')
                        manifest[item_id] = full_href
                
                # Get spine
                for itemref in opf_tree.xpath('//opf:spine/opf:itemref', namespaces={'opf': ns['opf']}):
                    idref = itemref.get('idref')
                    if idref and idref in manifest:
                        self.spine_items.append(manifest[idref])
                
                if not self.spine_items:
                    self.error = True
                    return

                # Calculate lengths
                for spine_item in self.spine_items:
                    try:
                        content = epub_zip.read(spine_item).decode('utf-8', errors='ignore')
                        try:
                            html_tree = etree.fromstring(content.encode('utf-8'))
                            text_content = ''.join(html_tree.itertext())
                            char_count = len(text_content.strip())
                        except etree.XMLSyntaxError:
                            text_content = re.sub(r'<[^>]+>', '', content)
                            char_count = len(text_content.strip())
                        self.chapter_lengths.append(char_count)
                    except Exception:
                        self.chapter_lengths.append(0)
                
                self.total_chars = sum(self.chapter_lengths)
                self.initialized = True

        except Exception as e:
            log.error(f"Error initializing EPUB calculator: {e}")
            self.error = True

    def calculate(self, chapter_filename: str, chapter_progress: float):
        if not self.initialized:
            self._initialize()
        
        if self.error or self.total_chars == 0:
            return None

        normalized_chapter = chapter_filename.replace('\\', '/')
        target_chapter_index = None
        
        for idx, spine_item in enumerate(self.spine_items):
            if normalized_chapter in spine_item or spine_item.endswith(normalized_chapter):
                target_chapter_index = idx
                break
        
        if target_chapter_index is None:
            return None
        
        chars_before = sum(self.chapter_lengths[:target_chapter_index])
        chars_in_chapter = self.chapter_lengths[target_chapter_index]
        chars_read = chars_before + (chars_in_chapter * chapter_progress)
        
        return (chars_read / self.total_chars) * 100


def process_annotation_for_sync(annotation, book, existing_syncs=None, progress_calculator=None):
    """
    Process a single annotation and store in database.
    
    Args:
        annotation: Annotation dict from Kobo
        book: Calibre book object
        existing_syncs: Optional dict of {annotation_id: sync_record} for batch processing
        progress_calculator: EpubProgressCalculator instance for this book
    
    Returns:
        True if stored successfully, False otherwise
    """
    annotation_id = annotation.get('id')
    highlighted_text = annotation.get('highlightedText')
    note_text = annotation.get('noteText')
    highlight_color = annotation.get('highlightColor')
    annotation_type = annotation.get('type', 'highlight')

    # Skip if no text content
    if not highlighted_text and not note_text:
        log.warning("Skipping annotation with no text content")
        return False

    # Check if already synced
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
    
    # Check if content has changed
    if existing_annotation and existing_sync:
        if (existing_annotation.highlighted_text == highlighted_text and 
            existing_annotation.note_text == note_text and 
            existing_annotation.highlight_color == highlight_color):
            log.debug(f"Annotation {annotation_id} unchanged, skipping")
            return False
    
    # Calculate progress
    progress_percent = None
    chapter_filename = annotation.get('location', {}).get('span', {}).get('chapterFilename')
    chapter_progress = annotation.get('location', {}).get('span', {}).get('chapterProgress', 0)
    
    if progress_calculator and chapter_filename:
        progress_percent = progress_calculator.calculate(chapter_filename, chapter_progress)
        if progress_percent is None:
            log.warning(f"Failed to calculate exact progress for annotation in book '{book.title}' (ID: {book.id})")

    # Extract location data
    location = annotation.get('location', {}).get('span', {})
    location_value = None
    location_type = None
    location_source = None
    
    if location:
        # Try to get location info from start path
        start_path = location.get('startPath')
        if start_path:
            location_value = start_path
            location_type = 'xpath'
            location_source = 'kobo'

    try:
        if existing_annotation:
            # Update existing annotation
            existing_annotation.highlighted_text = highlighted_text
            existing_annotation.note_text = note_text
            existing_annotation.highlight_color = highlight_color
            existing_annotation.annotation_type = annotation_type
            existing_annotation.chapter_filename = chapter_filename
            existing_annotation.chapter_progress = chapter_progress
            existing_annotation.progress_percent = progress_percent
            existing_annotation.location_value = location_value
            existing_annotation.location_type = location_type
            existing_annotation.location_source = location_source
            existing_annotation.last_modified = datetime.now(timezone.utc)
            log.info(f"Updated annotation {annotation_id} for book {book.id}")
        else:
            # Create new annotation
            new_annotation = ub.KoboAnnotation(
                user_id=current_user.id,
                book_id=book.id,
                annotation_id=annotation_id,
                annotation_type=annotation_type,
                highlighted_text=highlighted_text,
                note_text=note_text,
                highlight_color=highlight_color,
                location_value=location_value,
                location_type=location_type,
                location_source=location_source,
                chapter_filename=chapter_filename,
                chapter_progress=chapter_progress,
                progress_percent=progress_percent
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
@readingservices_api_v3.route("/content/<entitlement_id>/annotations", methods=["GET", "PATCH"])
@requires_reading_services_auth
def handle_annotations(entitlement_id):
    """
    Handle annotation requests for a specific book.
    GET: Retrieve all annotations for a book
    PATCH: Update/create annotations
    
    Future enhancement: Check if book exists locally and serve emulated response
    instead of always proxying to Kobo.
    """
    # TODO: Future emulation support
    # if request.method == "GET" and can_emulate_kobo_response(entitlement_id):
    #     return emulate_kobo_response('annotations', entitlement_id)
    
    # GET requests are proxied directly to Kobo at the end of the function
    # We only intercept PATCH requests to sync changes to local database
    if request.method == "PATCH":
        try:
            data = request.get_json()
            log_annotation_data(entitlement_id, "PATCH", data)

            # Get book from database
            book = get_book_by_entitlement_id(entitlement_id)
            if not book:
                log.warning(f"Book not found for entitlement {entitlement_id}, skipping local sync")
            else:
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
                    
                    # Initialize progress calculator once per book
                    progress_calculator = EpubProgressCalculator(book)

                    for annotation in annotations:
                        process_annotation_for_sync(
                            annotation=annotation, 
                            book=book, 
                            existing_syncs=existing_syncs,
                            progress_calculator=progress_calculator
                        )

        except Exception as e:
            log.error(f"Error processing PATCH annotations: {e}")
            import traceback
            log.error(traceback.format_exc())

    # Proxy to Kobo reading services
    return proxy_to_kobo_reading_services()


@csrf.exempt
@readingservices_api_v3.route("/content/checkforchanges", methods=["POST"])
@requires_reading_services_auth
def handle_check_for_changes():
    """
    Handle check for changes request.
    Proxies to Kobo's reading services.
    """
    return proxy_to_kobo_reading_services()


@csrf.exempt
@readingservices_userstorage.route("/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@requires_reading_services_auth
def handle_user_storage(subpath):
    """
    Handle UserStorage API requests (e.g., /api/UserStorage/Metadata).
    Proxies to Kobo's reading services.
    """
    return proxy_to_kobo_reading_services()


@csrf.exempt
@readingservices_api_v3.route("/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@requires_reading_services_auth
def handle_unknown_reading_service_request(subpath):
    """
    Catch-all handler for any reading services requests not explicitly handled.
    Logs the request and proxies to Kobo's reading services.
    """
    return proxy_to_kobo_reading_services()
