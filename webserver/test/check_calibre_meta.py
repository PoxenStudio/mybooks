#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import sys
import os

# Setup Calibre paths
path = os.environ.get('CALIBRE_PYTHON_PATH', '/usr/lib/calibre')
if path not in sys.path:
    sys.path.insert(0, path)

sys.resources_location = os.environ.get('CALIBRE_RESOURCES_PATH', '/usr/share/calibre')
sys.extensions_location = os.environ.get('CALIBRE_EXTENSIONS_PATH', '/usr/lib/calibre/calibre/plugins')
sys.executables_location = os.environ.get('CALIBRE_EXECUTABLES_PATH', '/usr/bin')

READING_STATUS_KEY = 'reading_status'

try:
    from calibre.db.legacy import LibraryDatabase
except ImportError:
    print("Error: Could not import calibre. Please ensure you are running this in an environment with calibre installed.")
    sys.exit(1)

def main():
    if len(sys.argv) < 4:
        print("Usage: python check_calibre_meta.py <library_path> <title> <set|get> [value]")
        sys.exit(1)

    library_path = sys.argv[1]
    title = sys.argv[2]
    operation = sys.argv[3]
    value = sys.argv[4] if len(sys.argv) > 4 else None

    if not os.path.exists(library_path):
        print(f"Error: Library path '{library_path}' does not exist.")
        sys.exit(1)

    try:
        db = LibraryDatabase(os.path.expanduser(library_path))
        cache = db.new_api
    except Exception as e:
        print(f"Error initializing database: {e}")
        sys.exit(1)

    # Show calibre library info
    print(f"Library Path: {library_path}")
    print(f"Number of books in library: {len(cache.all_book_ids())}")
    print("Field Metadata:")
    for key, meta in cache.field_metadata.items():
        print(f"  Key: {key}, Label: {meta.get('label')}, Name: {meta.get('name')}")
    print("")

    # Search for the book
    print(f"Searching for book with title: '{title}'...")
    ids = cache.search(f'title:"{title}"')

    if not ids:
        print(f"No book found with title '{title}'")
        return

    # Use the first found book
    book_id = list(ids)[0]
    print(f"Found book ID: {book_id}")

    # Find the custom field key for 'reading_status'
    target_label = READING_STATUS_KEY
    field_key = None

    # Check metadata for the custom field
    for key, meta in cache.field_metadata.items():
        if key.startswith('#') and meta.get('label') == target_label.lstrip('#'):
            field_key = key
            break

    if not field_key:
        print(f"Custom field with label '{target_label}' not found. Attempting to create it...")
        try:
            # Ensure label does not have a leading '#' as Calibre adds it automatically
            cache.create_custom_column(
                label=target_label.lstrip('#'),
                name='Reading Status',
                datatype='int',
                is_multiple=False
            )
            print(f"Created custom field '{target_label}'.")

            # Re-scan for the new key
            for key, meta in cache.field_metadata.items():

                if key.startswith('#') and meta.get('label') == target_label.lstrip('#'):
                    field_key = key
                    break

            if not field_key:
                print("Error: Custom field created but key not found in metadata.")
                return

        except Exception as e:
            print(f"Error creating custom field: {e}")
            print("Available custom fields:")
            for key, meta in cache.field_metadata.items():
                if key.startswith('#'):
                    print(f"  Key: {key}, Label: {meta.get('label')}, Name: {meta.get('name')}")
            return

    print(f"Found custom field key: {field_key}")

    if operation == 'get':
        current_val = cache.field_for(field_key, book_id)
        print(f"Current value of '{target_label}' (ID: {book_id}): {current_val}")

    elif operation == 'set':
        if value is None:
            print("Error: 'set' operation requires a value.")
            sys.exit(1)

        try:
            int_value = int(value)
        except ValueError:
            print(f"Error: Value '{value}' must be an integer.")
            sys.exit(1)

        print(f"Setting '{target_label}' to {int_value} for book ID {book_id}...")
        cache.set_field(field_key, {book_id: int_value})

        # Verify the change
        new_val = cache.field_for(field_key, book_id)
        print(f"New value of '{target_label}': {new_val}")

    else:
        print(f"Error: Unknown operation '{operation}'. Use 'set' or 'get'.")
        sys.exit(1)

if __name__ == "__main__":
    main()
